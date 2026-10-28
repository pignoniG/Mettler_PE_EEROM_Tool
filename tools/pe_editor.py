"""Editing model behind pe_eeprom_gui.py - no GUI code, so it can be unit-tested.

An Editor holds one 32-byte image in DUMP order (file byte numbers), an undo history and a change log. Fields are edited
in the firmware's byte order through pe_eeprom.modify(). With `auto_repair` on, every edit leaves the checksum bytes
valid (file bytes 6, 10 and 30); a deliberate edit of a checksum byte is left alone so an invalid image can still be made.
"""
import os

import pe_eeprom as pe

# colour regions by FILE byte; the checksum bytes are file bytes 6, 10 and 30 (firmware bytes 7, 11 and 31)
CHECKSUM_BYTES = (6, 10, 30)


def region(i):
    if i in CHECKSUM_BYTES:
        return 'checksum'
    if i <= 1:
        return 'scratch'
    if i <= 3:
        return 'unit'
    if i <= 7:
        return 'record 1'
    if i <= 11:
        return 'record 2'
    if i <= 19:
        return 'unused'
    return 'template'


class Editor:
    def __init__(self):
        self.data = bytes(pe.SIZE)
        self.orig = self.data
        self.path = None
        self.swapped = False
        self.auto_repair = True
        self.history = []                      # [(data, description)] for undo
        self.log = []
        self.other = None                      # image being compared against, or None

    # ------------------------------------------------------------------ file handling
    def open(self, path):
        data, swapped = pe.load(path)
        self.data = self.orig = bytes(data)
        self.path, self.swapped = path, swapped
        self.history.clear()
        self.log = [f'opened {os.path.basename(path)}' + (' (file was in firmware word order, turned around)' if swapped else '')]

    def new_blank(self):
        self.data = self.orig = bytes(pe.SIZE)
        self.path, self.swapped = None, False
        self.history.clear()
        self.log = ['new image']

    def save(self, path):
        pe.save(path, self.data, self.swapped)
        self.log.append(f'saved {os.path.basename(path)}')
        self.path = path

    def revert(self):
        if self.data != self.orig:
            self._push('revert')
            self.data = self.orig
            self.log.append('reverted to the file as opened')

    # ------------------------------------------------------------------ status
    def validity(self):
        return {k: (v == pe.GOOD, v) for k, v in pe.sums(self.data).items()}

    def is_valid(self):
        return pe.valid(self.data)

    def changed_bytes(self):
        return [i for i in range(pe.SIZE) if self.data[i] != self.orig[i]]

    def differing_from_other(self):
        return [] if self.other is None else [i for i in range(pe.SIZE) if self.data[i] != self.other[i]]

    def closest(self, n=3):
        return pe.closest(self.data, n)

    def fields(self):
        return pe.fields(self.data)

    # ------------------------------------------------------------------ editing
    def _push(self, desc):
        self.history.append((self.data, desc))

    def _commit(self, new, desc, repair=True):
        new = bytes(new)
        if self.auto_repair and repair:
            new = pe.repair(new)
        if new == self.data:
            return False
        ch = [i for i in range(pe.SIZE) if new[i] != self.data[i]]
        self._push(desc)
        old = self.data
        self.data = new
        self.log.append(desc + ': ' + ', '.join(f'byte {i} {old[i]:02X}->{new[i]:02X}' for i in ch))
        return True

    def undo(self):
        if not self.history:
            return False
        self.data, desc = self.history.pop()
        self.log.append(f'undid: {desc}')
        return True

    def set_byte(self, i, v):
        """Raw edit of a file byte. Editing a checksum byte is left as typed; any other byte repairs the checksums."""
        if not 0 <= v <= 255:
            raise ValueError('byte value must be 0-255')
        n = bytearray(self.data)
        n[i] = v
        return self._commit(n, f'byte {i} = {v:02X}', repair=i not in CHECKSUM_BYTES)

    def repair(self):
        new = pe.repair(self.data)
        if new == self.data:
            return False
        ch = [i for i in range(pe.SIZE) if new[i] != self.data[i]]
        self._push('repair checksums')
        self.log.append('repair checksums: ' + ', '.join(f'byte {i} {self.data[i]:02X}->{new[i]:02X}' for i in ch))
        self.data = new
        return True

    def _fw(self, fn, desc):
        return self._commit(pe.modify(self.data, fn), desc)

    def set_record(self, which, value):
        if not 0 <= value <= 0xFFFFFF:
            raise ValueError('value must fit in 24 bits')
        return self._commit(pe.set_record(self.data, which, value), f'calibration record {which} = {value}', repair=False)

    def set_x(self, value):
        return self._fw(lambda r: pe.put24(r, 22, value), f'calibration weight X = {value} units')

    def set_limit(self, value):
        return self._fw(lambda r: pe.put24(r, 25, value), f'range limit = {value} units')

    def set_window_half(self, on):
        def f(r):
            r[27] = (r[27] | 0x80) if on else (r[27] & 0x7F)
        return self._fw(f, f'calibration window X/{2 if on else 32}')

    def _bits(self, idx, mask, shift, value, desc):
        def f(r):
            r[idx] = (r[idx] & ~(mask << shift) & 255) | ((value & mask) << shift)
        return self._fw(f, desc)

    def set_test_mode(self, on):
        return self._bits(20, 1, 6, int(on), f'Test mode {"on" if on else "off"} (file byte 21 bit 6)')

    def set_learn(self, on):
        return self._bits(20, 1, 7, int(on), f'learn X on calibration {"on" if on else "off"} (file byte 21 bit 7)')

    def set_threshold_idx(self, v):
        return self._bits(20, 3, 0, v, f'threshold index {v} (file byte 21 bits 0-1)')

    def set_band_idx(self, v):
        return self._bits(20, 3, 2, v, f'stability band index {v} (file byte 21 bits 2-3)')

    def set_filter_row(self, v):
        return self._bits(20, 3, 4, v, f'filter row {v} (file byte 21 bits 4-5)')

    def set_code(self, v):
        return self._bits(21, 7, 0, v, f'decimal-point code {v} (file byte 20 bits 0-2)')

    def deltadisplay_off(self):
        """The DeltaDisplay option: file byte 31 = 7F arms it, file byte 29 bit 3 clear switches DeltaDisplay off."""
        def f(r):
            if (r[30] & 0x7F) != 0x7F:
                r[30] = 0x7F
            r[28] &= ~0x08 & 255
        return self._fw(f, 'DeltaDisplay off (file byte 29 bit 3 clear, byte 31 = 7F)')

    def deltadisplay_on(self):
        return self._fw(lambda r: r.__setitem__(28, r[28] | 0x08), 'DeltaDisplay on (file byte 29 bit 3 set)')

    def set_stability_detector(self, on):
        return self._fw(lambda r: pe.set_option_bit(r, 4, on), f'stability detector (SD) {"on" if on else "off"} (file byte 29 bit 4)')

    def set_auto_zero(self, on):
        return self._fw(lambda r: pe.set_option_bit(r, 5, on), f'auto zero {"on" if on else "off"} (file byte 29 bit 5)')

    def set_fine_range(self, digits):
        return self._fw(lambda r: pe.set_fine_range(r, digits), f'DeltaRange fine range = {digits} digits (file bytes 29, 28, 31)')

    def fine_range_off(self):
        return self._fw(pe.set_fine_range_off, 'DeltaRange off (file byte 31 = 7F, byte 28 = FF)')

    def deltadisplay_option_off(self):
        return self.fields()['dd_option_off']

    def apply_template(self, name):
        t = next((t for t in pe.load_templates() if t['name'] == name), None)
        if t is None:
            raise KeyError(name)
        b23, b2031 = pe.template_bytes(t)
        n = bytearray(self.data)
        n[2:4], n[20:32] = b23, b2031                   # the scale's own calibration records are kept
        return self._commit(n, f'applied template {name} (file bytes 2-3 and 20-31)')

    def build_new(self, name, donor=None):
        """Start a new image from a template; calibration records from `donor` bytes or zero."""
        self.new_blank()
        t = next(t for t in pe.load_templates() if t['name'] == name)
        b23, b2031 = pe.template_bytes(t)
        d = bytearray(pe.SIZE)
        d[2:4], d[20:32] = b23, b2031
        d = bytes(d)
        if donor is not None:
            d = d[:4] + bytes(donor[4:12]) + d[12:]
        else:
            d = pe.set_record(pe.set_record(d, 1, 0), 2, 0)
        self.data = self.orig = pe.repair(d)
        self.log = [f'built from template {name}; records ' + ('copied from a donor dump' if donor is not None else
                                                                'ZERO (untested on hardware)')]

    # ------------------------------------------------------------------ interchange
    def to_words(self):
        return ' '.join(f'{self.data[i]:02X}{self.data[i + 1]:02X}' for i in range(0, pe.SIZE, 2))

    def from_words(self, text):
        words = text.replace(',', ' ').split()
        if len(words) != 16 or any(len(w) != 4 for w in words):
            raise ValueError('expected 16 words of 4 hex digits')
        new = bytes.fromhex(''.join(words))
        self._push('pasted words')
        self.data = new
        self.log.append('pasted 16 words' + ('' if pe.valid(new) else ' (checksums do not verify)'))

    def set_other(self, path_or_none):
        if path_or_none is None:
            self.other = None
            return
        self.other, _ = pe.load(path_or_none)
