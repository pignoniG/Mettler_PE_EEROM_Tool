#!/usr/bin/env python3
"""Editor for the 32-byte parameter EEPROM (MCM2801) dumps of Mettler PE balances.

    python3 tools/pe_eeprom_gui.py [dump.bin]

Only the standard library (tkinter) is used. Nothing is written to disk until you choose Save as.
The format and the meaning of the fields are documented in EEPROM_MAP.md.
"""
import argparse
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pe_eeprom as pe                       # noqa: E402
from pe_editor import Editor, region        # noqa: E402

COLORS = {'scratch': '#e4e4e4', 'unit': '#d4d4d4', 'record 1': '#cde2ff', 'record 2': '#c6efef',
          'unused': '#ffffff', 'template': '#fff1b8', 'checksum': '#ffd2a0'}
GOOD, BAD = '#2e8b2e', '#c0392b'
MONO = ('Menlo', 12) if sys.platform == 'darwin' else ('Courier New', 11)

# byte numbers are FILE (dump) byte numbers; the firmware reads each 16-bit word low byte first, so file bytes 2k, 2k+1
# are firmware bytes 2k+1, 2k
BYTE_HELP = {0: 'scratch: down-counter saved on standby (firmware byte 1); not configuration',
             1: 'scratch: firmware flag register saved on standby (firmware byte 0); not configuration',
             2: 'unit word, low half (80 in all known dumps)',
             3: 'unit word: high nibble = the unit the user selected (a user setting)',
             6: 'CHECKSUM of calibration record 1 (file bytes 4-7 must sum to 0xAB)',
             10: 'CHECKSUM of calibration record 2 (file bytes 8-11 must sum to 0xAB)',
             20: 'bits 0-2 decimal-point code (with the unit); code 5 = integer display, 6/7 = Error',
             21: 'bits 0-1 threshold, 2-3 stability band, 4-5 filter row, 6 TEST MODE (display x2), 7 learn-X',
             28: 'unknown (FF in all known dumps)',
             29: 'bit 3 = DeltaDisplay option bit (clear it, with byte 31 = 7F, to switch DeltaDisplay off); F8 in the family',
             30: 'CHECKSUM of the template (file bytes 20-31 must sum to 0xAB)',
             31: 'option gate: 7F in all known dumps (arms the option in byte 29)'}
for _i in (4, 5, 7): BYTE_HELP[_i] = 'calibration record 1 (24-bit, least significant first: bytes 5, 4, 7): the live calibration factor'
for _i in (8, 9, 11): BYTE_HELP[_i] = 'calibration record 2 (bytes 9, 8, 11): saved / factory copy of the calibration factor'
for _i in range(12, 20): BYTE_HELP[_i] = 'unused: zero in all known dumps'
for _i in (23, 22, 25): BYTE_HELP[_i] = 'X = calibration weight in internal units (1/8 display digit); LSB first: bytes 23, 22, 25'
for _i in (24, 27, 26): BYTE_HELP[_i] = 'range limit (bytes 24, 27, 26); byte 26 bit 7 = calibration window X/2 (clear = X/32)'


class App:
    def __init__(self, root, path=None):
        self.root = root
        self.ed = Editor()
        self.saved = self.ed.data
        root.title('Mettler PE EEPROM editor')
        root.minsize(1000, 620)
        self.cells, self.vars = [], {}
        self._build_menu()
        self._build_ui()
        root.protocol('WM_DELETE_WINDOW', self.quit)
        mod = 'Command' if sys.platform == 'darwin' else 'Control'
        root.bind(f'<{mod}-o>', lambda e: self.open())
        root.bind(f'<{mod}-s>', lambda e: self.save_as())
        root.bind(f'<{mod}-z>', lambda e: self.undo())
        if path:
            self.open(path)
        else:
            self.refresh()

    # ---------------------------------------------------------------- construction
    def _build_menu(self):
        m = tk.Menu(self.root)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label='Open...', command=self.open)
        f.add_command(label='Save as...', command=self.save_as)
        f.add_command(label='Revert to file as opened', command=self.revert)
        f.add_separator()
        f.add_command(label='New image from template...', command=self.build_dialog)
        f.add_separator()
        f.add_command(label='Quit', command=self.quit)
        m.add_cascade(label='File', menu=f)
        e = tk.Menu(m, tearoff=0)
        e.add_command(label='Undo', command=self.undo)
        e.add_command(label='Repair checksums', command=self.repair)
        e.add_separator()
        e.add_command(label='Copy as 16 words', command=self.copy_words)
        e.add_command(label='Paste 16 words...', command=self.paste_words)
        m.add_cascade(label='Edit', menu=e)
        self.root.config(menu=m)

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(8, 6))
        top.pack(fill='x')
        for text, cmd in (('Open...', self.open), ('Save as...', self.save_as), ('Revert', self.revert),
                          ('Undo', self.undo)):
            ttk.Button(top, text=text, command=cmd).pack(side='left', padx=(0, 4))
        ttk.Separator(top, orient='vertical').pack(side='left', fill='y', padx=6)
        for text, cmd in (('Copy as words', self.copy_words), ('Paste words...', self.paste_words),
                          ('Compare with file...', self.compare), ('Clear compare', lambda: self.compare(clear=True))):
            ttk.Button(top, text=text, command=cmd).pack(side='left', padx=(0, 4))
        self.file_label = ttk.Label(top, text='no file')
        self.file_label.pack(side='left', padx=10)
        self.badge = tk.Label(top, text='', fg='white', padx=10, pady=2, font=(None, 11, 'bold'))
        self.badge.pack(side='right')

        body = ttk.Frame(self.root, padding=(8, 0))
        body.pack(fill='both', expand=True)
        left = ttk.Frame(body)
        left.pack(side='left', fill='both', expand=True)
        right = ttk.Frame(body, padding=(10, 0, 0, 0))
        right.pack(side='left', fill='y')

        # ---- byte grid
        g = ttk.LabelFrame(left, text='EEPROM image - 32 bytes (hex); click a byte to edit it', padding=6)
        g.pack(fill='x')
        for c in range(8):
            ttk.Label(g, text=str(c), foreground='#777').grid(row=0, column=c + 1)
        for r in range(4):
            ttk.Label(g, text=f'{r * 8:2d}', foreground='#777').grid(row=r + 1, column=0, padx=(0, 4))
            for c in range(8):
                i = r * 8 + c
                v = tk.StringVar()
                en = tk.Entry(g, textvariable=v, width=3, justify='center', font=MONO, relief='solid', bd=1,
                              highlightthickness=2, highlightbackground='white', highlightcolor='#3b7ddd')
                en.grid(row=r + 1, column=c + 1, padx=2, pady=2)
                en.bind('<Return>', lambda e, i=i: self.cell_commit(i))
                en.bind('<FocusOut>', lambda e, i=i: self.cell_commit(i))
                en.bind('<FocusIn>', lambda e, i=i: self.hint_var.set(f'byte {i}: {BYTE_HELP.get(i, "")}'))
                self.cells.append(en)
                self.vars[i] = v
        leg = ttk.Frame(g)
        leg.grid(row=5, column=0, columnspan=9, sticky='w', pady=(6, 0))
        for name in ('scratch', 'unit', 'record 1', 'record 2', 'unused', 'template', 'checksum'):
            tk.Label(leg, text=f' {name} ', bg=COLORS[name], fg='black', relief='solid', bd=1, font=(None, 9)).pack(side='left', padx=2)
        self.hint_var = tk.StringVar(value='')
        ttk.Label(left, textvariable=self.hint_var, foreground='#444', wraplength=560, justify='left').pack(
            anchor='w', pady=(4, 0))

        # ---- integrity
        ig = ttk.LabelFrame(left, text='Integrity - every block must sum to 0xAB', padding=6)
        ig.pack(fill='x', pady=(8, 0))
        self.sum_labels = {}
        for r, name in enumerate(('record 1 (bytes 4-7)', 'record 2 (bytes 8-11)', 'template (bytes 20-31)')):
            ttk.Label(ig, text=name, width=24).grid(row=r, column=0, sticky='w')
            sl = ttk.Label(ig, text='', width=10)
            sl.grid(row=r, column=1)
            st = tk.Label(ig, text='', width=6, fg='white')
            st.grid(row=r, column=2, padx=4, pady=1)
            self.sum_labels[name] = (sl, st)
        opt = ttk.Frame(ig)
        opt.grid(row=3, column=0, columnspan=3, sticky='w', pady=(6, 0))
        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text='Auto-repair after each edit', variable=self.auto_var,
                        command=lambda: setattr(self.ed, 'auto_repair', self.auto_var.get())).pack(side='left')
        ttk.Label(opt, text='   (checksum bytes: file 6, 10, 30)', foreground='#555').pack(side='left')
        ttk.Button(opt, text='Repair checksums', command=self.repair).pack(side='left', padx=10)

        # ---- log
        lg = ttk.LabelFrame(left, text='Changes', padding=4)
        lg.pack(fill='both', expand=True, pady=(8, 0))
        self.log = tk.Text(lg, height=7, wrap='word', state='disabled', font=(None, 10))
        sb = ttk.Scrollbar(lg, command=self.log.yview)
        self.log.config(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.log.pack(side='left', fill='both', expand=True)

        # ---- right: records
        rg = ttk.LabelFrame(right, text='Calibration records (24-bit, least significant byte first)', padding=6)
        rg.pack(fill='x')
        self.rec_vars = {}
        for r, w in enumerate((1, 2)):
            ttk.Label(rg, text=f'Record {w}' + ('  (live)' if w == 1 else '  (saved copy)')).grid(row=r, column=0, sticky='w')
            v = tk.StringVar()
            ttk.Entry(rg, textvariable=v, width=11).grid(row=r, column=1, padx=4, pady=2)
            dec = ttk.Label(rg, text='', width=11)
            dec.grid(row=r, column=2)
            ttk.Button(rg, text='Set', width=4, command=lambda w=w: self.set_record(w)).grid(row=r, column=3)
            self.rec_vars[w] = (v, dec)

        # ---- right: parameters, grouped and explained
        nb = ttk.Notebook(right)
        nb.pack(fill='x', pady=(8, 0))
        disp = ttk.Frame(nb, padding=6)
        cal = ttk.Frame(nb, padding=6)
        resp = ttk.Frame(nb, padding=6)
        nb.add(disp, text='Display')
        nb.add(cal, text='Calibration')
        nb.add(resp, text='Response')
        self.test_var, self.learn_var, self.win_var = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()

        def note(parent, row, text):
            ttk.Label(parent, text=text, foreground='#555', font=(None, 9), wraplength=400, justify='left').grid(
                row=row, column=0, columnspan=4, sticky='w', pady=(0, 8))

        # -- Display
        self.dd_label = ttk.Label(disp, text='', font=(None, 10, 'bold'))
        self.dd_label.grid(row=0, column=0, columnspan=4, sticky='w')
        ttk.Button(disp, text='DeltaDisplay OFF', command=lambda: self.ed_apply(self.ed.deltadisplay_off)).grid(row=1, column=0, sticky='w')
        ttk.Button(disp, text='DeltaDisplay ON', command=lambda: self.ed_apply(self.ed.deltadisplay_on)).grid(row=1, column=1, sticky='w', padx=4)
        note(disp, 2, 'DeltaDisplay blanks the last digit while the reading is still moving (the PE11/PE16 "delta" display). OFF clears '
                      'bit 3 of byte 29 (with byte 31 = 7F) and leaves everything else alone - confirmed on a real PE6000.')
        ttk.Label(disp, text='Decimal-point code (byte 20 bits 0-2)').grid(row=3, column=0, columnspan=2, sticky='w')
        self.res_var = tk.StringVar()
        ttk.Spinbox(disp, from_=0, to=7, width=4, textvariable=self.res_var, command=self.res_changed).grid(row=3, column=2, sticky='w')
        note(disp, 4, 'Where the decimal point sits for the selected unit, i.e. the readability. For grams: 4 = 1 decimal (0.1 g), 5 = no '
                      'decimal (also silences DeltaDisplay), 6 and 7 = Error. Changing it re-scales what the display shows, not the weighing.')
        self.pilot_var, self.az_var = tk.BooleanVar(), tk.BooleanVar()
        ttk.Checkbutton(disp, text='Unstable-reading pilot (leftmost segment)', variable=self.pilot_var,
                        command=lambda: self.ed_apply(self.ed.set_pilot, self.pilot_var.get())).grid(row=9, column=0, columnspan=4, sticky='w')
        note(disp, 10, 'File byte 29 bit 4: the stability-detector pilot, a segment in the leftmost position that lights while the reading moves. Off = never lights.')
        ttk.Checkbutton(disp, text='Auto zero', variable=self.az_var,
                        command=lambda: self.ed_apply(self.ed.set_auto_zero, self.az_var.get())).grid(row=11, column=0, columnspan=4, sticky='w')
        note(disp, 12, 'File byte 29 bit 5: slowly tracks the zero reading in steps of 1/8 digit while the reading stays inside a small band around zero. Off = zero only changes with TARE. (The service manual lists 'no auto zero' for Test mode.)')
        ttk.Label(disp, text='DeltaRange fine range (digits)').grid(row=5, column=0, columnspan=2, sticky='w')
        self.fine_var = tk.StringVar()
        ttk.Entry(disp, textvariable=self.fine_var, width=9).grid(row=5, column=2, sticky='w')
        ttk.Button(disp, text='Set', width=4, command=self.set_fine).grid(row=5, column=3, sticky='w')
        ttk.Button(disp, text='Off', width=4, command=lambda: self.ed_apply(self.ed.fine_range_off)).grid(row=5, column=4, sticky='w')
        note(disp, 6, 'DeltaRange (PE360/PE3600): below this reading the full resolution is shown, above it the last digit is blanked (coarse range). Stored in file bytes 29, 28 and 31, '
                      'so it excludes the DeltaDisplay option bit. Off = 7F in byte 31, as on the PE3000/PE6000/PE16.')
        ttk.Checkbutton(disp, text='Test (service) mode: display x2', variable=self.test_var,
                        command=lambda: self.ed_apply(self.ed.set_test_mode, self.test_var.get())).grid(row=7, column=0, columnspan=4, sticky='w')
        note(disp, 8, 'From the service manual: doubles the indicated value to make adjustments easier. Leave OFF for normal use.')

        # -- Calibration
        self.x_var, self.lim_var = tk.StringVar(), tk.StringVar()
        for r, (lab, var, fn) in enumerate((('Calibration weight (digits)', self.x_var, self.set_x),
                                            ('Overload limit (digits)', self.lim_var, self.set_limit))):
            ttk.Label(cal, text=lab).grid(row=r * 2, column=0, sticky='w')
            ttk.Entry(cal, textvariable=var, width=11).grid(row=r * 2, column=1, sticky='w', padx=4)
            ttk.Button(cal, text='Set', width=4, command=fn).grid(row=r * 2, column=2, sticky='w')
            note(cal, r * 2 + 1, ('The weight the balance asks for when you calibrate, in display digits (this is what distinguishes Normal from Certification mode; a certified balance additionally has jumper ST4 fitted, which blocks calibration in hardware): 10000 digits at 0.1 g = 1 kg, '
                                  '30000 = 3 kg. Calibration is refused if the weight on the pan is outside the window below.' if r == 0 else
                                  'Reading above which the balance shows overload, in display digits (about capacity + 3 %).'))
        ttk.Checkbutton(cal, text='Wide calibration window (+-50 % instead of +-3.1 %)', variable=self.win_var,
                        command=lambda: self.ed_apply(self.ed.set_window_half, self.win_var.get())).grid(row=4, column=0, columnspan=4, sticky='w')
        note(cal, 5, 'How far the weight on the pan may be from the calibration weight and still be accepted. The new calibration factor '
                     'assumes the pan holds exactly the calibration weight, so a wide window does NOT let you calibrate with another weight '
                     'without error: set the weight above to the one you have instead.')
        ttk.Checkbutton(cal, text='Learn the weight on calibration (experimental)', variable=self.learn_var,
                        command=lambda: self.ed_apply(self.ed.set_learn, self.learn_var.get())).grid(row=6, column=0, columnspan=4, sticky='w')
        note(cal, 7, 'Calibration also copies the measured value into the calibration weight above (read from the firmware, never tried).')

        # -- Response
        self.thr_cb = self._combo(resp, 0, 'Threshold', [f'{i}  (0x{t:02X})' for i, t in enumerate(pe.THRESHOLDS)],
                                  self.ed.set_threshold_idx)
        note(resp, 1, 'Level used by the integration interrupt to decide how much the reading has moved. Seen on a real PE6000: a different '
                      'value made the last-digit blanking less sensitive, not absent. Index 3 (0xC2) made the emulated display unreadable - avoid.')
        self.band_cb = self._combo(resp, 2, 'Stability band', [f'{i}  ({b})' for i, b in enumerate(pe.BANDS)],
                                   self.ed.set_band_idx)
        note(resp, 3, 'How much the reading may change and still count as stable (smaller = stricter, slower to settle: 2 settles ~10 % slower than 12 in the emulator).')
        self.row_cb = self._combo(resp, 4, 'Filter row', [str(i) for i in range(4)], self.ed.set_filter_row)
        note(resp, 5, 'Selects a row of the filter table; row 3 settles slightly earlier but converges slower in the emulator. No setting gives a real "fast mode".')

        # ---- right: templates
        cg = ttk.LabelFrame(right, text='Closest known models', padding=6)
        cg.pack(fill='x', pady=(8, 0))
        self.tree = ttk.Treeview(cg, columns=('diff',), height=3, selectmode='browse')
        self.tree.heading('#0', text='template')
        self.tree.heading('diff', text='differing file bytes (2-3, 20-29, 31)')
        self.tree.column('#0', width=120)
        self.tree.column('diff', width=240)
        self.tree.pack(fill='x')
        ttk.Button(cg, text='Apply selected template...', command=self.apply_template).pack(anchor='e', pady=(4, 0))

        ttk.Label(self.root, foreground='#555', font=(None, 9), padding=(8, 4),
                  text='Keep your original dump. After programming a modified image, calibrate the balance. '
                       'Nothing here can make an instrument certified.').pack(fill='x')

    def _combo(self, parent, row, label, values, setter):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', pady=(4, 0))
        cb = ttk.Combobox(parent, values=values, state='readonly', width=12)
        cb.grid(row=row, column=1, columnspan=2, sticky='w', pady=(4, 0))
        cb.bind('<<ComboboxSelected>>', lambda e: self.ed_apply(setter, cb.current()))
        return cb

    # ---------------------------------------------------------------- actions
    def ed_apply(self, fn, *args):
        try:
            fn(*args)
        except Exception as ex:                                     # noqa
            messagebox.showerror('Cannot apply', str(ex))
        self.refresh()

    def cell_commit(self, i):
        txt = self.vars[i].get().strip()
        try:
            v = int(txt, 16)
            if not 0 <= v <= 255:
                raise ValueError
        except ValueError:
            self.refresh()
            return
        if v != self.ed.data[i]:
            self.ed.set_byte(i, v)
        self.refresh()

    def res_changed(self):
        try:
            v = int(self.res_var.get())
            if 0 <= v <= 7:
                self.ed_apply(self.ed.set_code, v)
        except ValueError:
            self.refresh()

    def _num(self, text, maxv=0xFFFFFF):
        v = int(text.strip(), 0)
        if not 0 <= v <= maxv:
            raise ValueError('value must fit in 24 bits')
        return v

    def set_record(self, w):
        try:
            self.ed.set_record(w, self._num(self.rec_vars[w][0].get()))
        except ValueError as ex:
            messagebox.showerror('Invalid value', str(ex))
        self.refresh()

    def set_x(self):
        try:
            self.ed.set_x(round(float(self.x_var.get()) * 8))
        except ValueError as ex:
            messagebox.showerror('Invalid value', str(ex))
        self.refresh()

    def set_fine(self):
        try:
            self.ed.set_fine_range(int(float(self.fine_var.get())))
        except ValueError as ex:
            messagebox.showerror('Invalid value', str(ex))
        self.refresh()

    def set_limit(self):
        try:
            self.ed.set_limit(round(float(self.lim_var.get()) * 8))
        except ValueError as ex:
            messagebox.showerror('Invalid value', str(ex))
        self.refresh()

    def open(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(title='Open EEPROM dump',
                                              filetypes=[('EEPROM dumps', '*.bin *.BIN *.rom *.eep'), ('All files', '*')])
        if not path:
            return
        try:
            self.ed.open(path)
        except (OSError, SystemExit) as ex:
            messagebox.showerror('Cannot open', str(ex))
            return
        self.saved = self.ed.data
        self.refresh()

    def save_as(self):
        path = filedialog.asksaveasfilename(title='Save EEPROM dump as', defaultextension='.bin',
                                            initialfile=os.path.basename(self.ed.path or 'eeprom.bin'))
        if not path:
            return
        if not self.ed.is_valid() and not messagebox.askyesno(
                'Checksums are not valid', 'The balance will reject this image (ERROR). Save it anyway?'):
            return
        self.ed.save(path)
        self.saved = self.ed.data
        self.refresh()

    def revert(self):
        self.ed.revert()
        self.refresh()

    def undo(self):
        if not self.ed.undo():
            self.root.bell()
        self.refresh()

    def repair(self):
        self.ed.repair()
        self.refresh()

    def apply_template(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('Template', 'Select a template in the list first.')
            return
        name = self.tree.item(sel[0], 'text')
        if messagebox.askyesno('Apply template', f'Replace the model template (bytes 2-3 and 20-31) with {name}?\n'
                               'The calibration records of this scale are kept.'):
            self.ed.apply_template(name)
            self.refresh()

    def build_dialog(self):
        d = tk.Toplevel(self.root)
        d.title('New image from template')
        d.transient(self.root)
        ttk.Label(d, text='Template').grid(row=0, column=0, sticky='w', padx=8, pady=6)
        names = [t['name'] for t in pe.load_templates()]
        tcb = ttk.Combobox(d, values=names, state='readonly')
        tcb.current(0)
        tcb.grid(row=0, column=1, padx=8)
        mode = tk.StringVar(value='donor')
        ttk.Radiobutton(d, text='Copy the calibration records from a donor dump:', variable=mode, value='donor').grid(
            row=1, column=0, columnspan=2, sticky='w', padx=8)
        dv = tk.StringVar()
        ttk.Entry(d, textvariable=dv, width=40).grid(row=2, column=0, columnspan=2, padx=8)
        ttk.Button(d, text='Browse...', command=lambda: dv.set(filedialog.askopenfilename(parent=d) or dv.get())).grid(
            row=2, column=2, padx=4)
        ttk.Radiobutton(d, text='Zero records (untested on hardware)', variable=mode, value='zero').grid(
            row=3, column=0, columnspan=2, sticky='w', padx=8, pady=4)

        def go():
            donor = None
            if mode.get() == 'donor':
                try:
                    donor, _ = pe.load(dv.get())
                except (OSError, SystemExit) as ex:
                    messagebox.showerror('Donor dump', str(ex), parent=d)
                    return
            self.ed.build_new(tcb.get(), donor)
            self.saved = self.ed.data
            d.destroy()
            self.refresh()
        ttk.Button(d, text='Build', command=go).grid(row=4, column=1, sticky='e', padx=8, pady=8)

    def copy_words(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.ed.to_words())

    def paste_words(self):
        txt = simpledialog.askstring('Paste words', '16 hex words, e.g. "0001 0080 30DF ...":', parent=self.root)
        if txt:
            try:
                self.ed.from_words(txt)
            except ValueError as ex:
                messagebox.showerror('Invalid', str(ex))
            self.refresh()

    def compare(self, clear=False):
        if clear:
            self.ed.set_other(None)
        else:
            path = filedialog.askopenfilename(title='Compare with...')
            if not path:
                return
            try:
                self.ed.set_other(path)
            except (OSError, SystemExit) as ex:
                messagebox.showerror('Cannot open', str(ex))
                return
            self.ed.log.append(f'comparing with {os.path.basename(path)}: ' +
                               (f'{len(self.ed.differing_from_other())} byte(s) differ (outlined red)'))
        self.refresh()

    def quit(self):
        if self.ed.data != self.saved and not messagebox.askyesno('Quit', 'There are unsaved changes. Quit anyway?'):
            return
        self.root.destroy()

    # ---------------------------------------------------------------- display
    def refresh(self):
        d, ed = self.ed.data, self.ed
        changed, diff = set(ed.changed_bytes()), set(ed.differing_from_other())
        for i, en in enumerate(self.cells):
            self.vars[i].set(f'{d[i]:02X}')
            en.config(bg=COLORS[region(i)], fg=BAD if i in changed else 'black',
                      highlightbackground='#e03030' if i in diff else 'white')
        for name, (sl, st) in self.sum_labels.items():
            ok, s = ed.validity()[name]
            sl.config(text=f'sum 0x{s:02X}')
            st.config(text='OK' if ok else 'BAD', bg=GOOD if ok else BAD)
        ok = ed.is_valid()
        self.badge.config(text='VALID - balance accepts it' if ok else 'INVALID - balance shows ERROR', bg=GOOD if ok else BAD)
        self.file_label.config(text=(os.path.basename(ed.path) if ed.path else 'new image') +
                               ('   (word-swapped file)' if ed.swapped else '') +
                               ('   *modified*' if d != self.saved else ''))
        f = ed.fields()
        for w, (v, dec) in self.rec_vars.items():
            val = f['record%d' % w]
            v.set(f'0x{val:06X}')
            dec.config(text=f'{val}')
        self.test_var.set(f['test_mode'])
        self.learn_var.set(f['learn'])
        self.thr_cb.current(f['threshold_idx'])
        self.band_cb.current(f['band_idx'])
        self.row_cb.current(f['filter_row'])
        self.res_var.set(str(f['code']))
        self.dd_label.config(text='DeltaDisplay (last-digit blanking): ' +
                             ('OFF via the option bit' if f['dd_option_off'] else
                              'ON' + (' (code 5 would also disable it, but moves the decimal point)' if f['code'] == 5 else '')))
        self.pilot_var.set(not f['pilot_off'])
        self.az_var.set(not f['auto_zero_off'])
        self.fine_var.set(f"{f['fine_range'] / 8:g}" if f['fine_range_active'] else 'off')
        self.x_var.set(f"{f['x'] / 8:g}")
        self.lim_var.set(f"{f['limit'] / 8:g}")
        self.win_var.set(f['window_half'])
        self.tree.delete(*self.tree.get_children())
        for n, name, dif, t in ed.closest(7)[:7]:
            self.tree.insert('', 'end', text=name, values=('identical' if not dif else f'{n}: ' + ', '.join(map(str, dif)),))
        self.log.config(state='normal')
        self.log.delete('1.0', 'end')
        self.log.insert('end', '\n'.join(ed.log))
        self.log.see('end')
        self.log.config(state='disabled')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file', nargs='?')
    ap.add_argument('--shot', help='save a screenshot of the window to this file and exit (testing)')
    a = ap.parse_args()
    root = tk.Tk()
    app = App(root, a.file)
    if a.shot:
        root.geometry('+60+60')
        root.update()
        root.lift()
        root.update()
        root.after(500, lambda: (os.system(f'screencapture -x -R60,60,{root.winfo_width()},{root.winfo_height()} "{a.shot}"'),
                                 root.destroy()))
    root.mainloop()


if __name__ == '__main__':
    main()
