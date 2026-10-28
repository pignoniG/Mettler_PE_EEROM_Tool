"""Drives the real tkinter widgets of pe_eeprom_gui.py. Needs a display; run by hand:  python3 tests/gui_smoke.py
(skipped silently when no display is available). Message boxes are stubbed so nothing blocks."""
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'tools'))
try:
    import tkinter as tk
    root = tk.Tk()
except Exception as ex:                                                # noqa
    print('no display, skipped:', ex)
    sys.exit(0)

import pe_eeprom as pe                    # noqa: E402
import pe_eeprom_gui as g                 # noqa: E402

g.messagebox.askyesno = lambda *a, **k: True
g.messagebox.showerror = lambda *a, **k: print('  (error box:', a[1], ')')
g.messagebox.showinfo = lambda *a, **k: None

EX = os.path.join(ROOT, 'examples')
app = g.App(root, os.path.join(EX, 'pe3000_B_french_original.bin'))
root.update()
fails = []


def check(name, cond):
    print(('ok   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


def badge():
    return app.badge.cget('text')


check('opens valid', badge().startswith('VALID'))
check('all 32 cells show the file', all(app.vars[i].get() == f'{app.ed.data[i]:02X}' for i in range(32)))

# type a byte into a cell and press Return - template byte, so the checksum byte follows
app.vars[22].set('38'); app.cell_commit(22); root.update()
check('cell edit applied and image still valid', app.ed.data[22] == 0x38 and badge().startswith('VALID'))
check('changed cell is flagged', str(app.cells[22].cget('fg')) in ('#c0392b',))
check('checksum cell followed (byte 30)', app.vars[30].get() == f'{app.ed.data[30]:02X}' and app.ed.data[30] != 0x2C)
app.vars[5].set('zz'); app.cell_commit(5); root.update()
check('invalid hex is rejected and the cell restored', app.vars[5].get() == f'{app.ed.data[5]:02X}')

# checkboxes / comboboxes / spinbox
app.test_var.set(True); app.ed_apply(app.ed.set_test_mode, True); root.update()
check('test mode sets file byte 21 bit 6', app.ed.data[21] & 0x40 and app.test_var.get())
app.band_cb.current(3); app.band_cb.event_generate('<<ComboboxSelected>>'); root.update()
check('band combobox sets file byte 21 bits 2-3', (app.ed.data[21] >> 2) & 3 == 3)
app.res_var.set('2'); app.res_changed(); root.update()
check('decimal-point code is file byte 20', app.ed.data[20] & 7 == 2 and 'ON' in app.dd_label.cget('text'))
app.ed_apply(app.ed.deltadisplay_off); root.update()
check('DeltaDisplay OFF clears byte 29 bit 3, byte 31 = 7F', not app.ed.data[29] & 8 and app.ed.data[31] & 0x7F == 0x7F
      and 'OFF' in app.dd_label.cget('text') and badge().startswith('VALID'))

# Set buttons
app.rec_vars[1][0].set('0x123456'); app.set_record(1); root.update()
check('record 1 set', app.ed.fields()['record1'] == 0x123456 and badge().startswith('VALID'))
app.rec_vars[2][0].set('not a number'); app.set_record(2); root.update()
check('bad record value does not change the image', app.ed.fields()['record2'] != 0)
app.x_var.set('1000'); app.set_x(); root.update()
check('X set (digits)', app.ed.fields()['x'] == 8000)

# template list + apply
app.refresh(); kids = app.tree.get_children()
check('template list filled', len(kids) == 7)
app.tree.selection_set([k for k in kids if app.tree.item(k, 'text') == 'PE16'][0]); app.apply_template(); root.update()
check('template applied, records kept', app.ed.data[21] == 0x21 and app.ed.fields()['record1'] == 0x123456 and badge().startswith('VALID'))

# undo everything, then a deliberately broken image shows INVALID
n = 0
while app.ed.undo(): n += 1
app.refresh(); root.update()
check(f'undo x{n} returns to the opened file', app.ed.data == app.ed.orig)
app.vars[6].set('00'); app.cell_commit(6); root.update()
check('editing a checksum byte directly shows INVALID', badge().startswith('INVALID'))
app.repair(); root.update()
check('Repair checksums fixes it', badge().startswith('VALID'))

# save + reopen
with tempfile.TemporaryDirectory() as td:
    out = os.path.join(td, 'o.bin')
    g.filedialog.asksaveasfilename = lambda **k: out
    app.vars[1].set('D0'); app.cell_commit(1)
    app.save_as(); root.update()
    with open(out, 'rb') as f:
        saved_byte1 = f.read()[1]
    check('save writes the file', saved_byte1 == 0xD0)
    g.filedialog.askopenfilename = lambda **k: os.path.join(EX, 'pe6000_own.bin')
    app.open(); root.update()
    check('open shows the other dump', app.ed.data[21] == 0x2C and app.file_label.cget('text').startswith('pe6000_own'))

# compare
g.filedialog.askopenfilename = lambda **k: os.path.join(EX, 'pe16_forum.bin')
app.compare(); root.update()
red = [i for i in range(32) if str(app.cells[i].cget('highlightbackground')) == '#e03030']
check('compare outlines the differing bytes', red == app.ed.differing_from_other() and len(red) > 5)
app.compare(clear=True); root.update()
check('clear compare', not any(str(app.cells[i].cget('highlightbackground')) == '#e03030' for i in range(32)))

# words
app.copy_words(); root.update()
check('copy as words puts 16 words on the clipboard', len(root.clipboard_get().split()) == 16)
g.simpledialog.askstring = lambda *a, **k: '0001 0080 30DF 8517 543D 0317 0000 0000 0000 0000 0421 E200 D004 138A FFF8 BD7F'
app.paste_words(); root.update()
with open(os.path.join(EX, 'pe16_forum.bin'), 'rb') as f:
    check('paste words loads the PE16 dump', f.read() == app.ed.data)

root.destroy()
print('\nFAILED: ' + ', '.join(fails) if fails else '\nall GUI checks passed')
sys.exit(1 if fails else 0)
