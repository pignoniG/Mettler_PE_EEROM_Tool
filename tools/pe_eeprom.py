#!/usr/bin/env python3
"""pe_eeprom - decode, verify, edit and rebuild the 32-byte parameter EEPROM (MCM2801 EAROM) of Mettler PE balances.

The format was read out of the CPU firmware (ME-47455 V4.1, INS8050); see EEPROM_MAP.md for the evidence.

BYTE ORDER - the thing to know first.  The firmware reads every 16-bit word low byte first, so the byte it calls RAM
0x20+i is byte  i XOR 1  of a normal dump (bytes 0<->1, 2<->3, ...).  The checksums cannot show this (they are blind to
swapping the two bytes of a word), but every quantity in the image only makes sense in the firmware's order: the
calibration weight, the range limit and the calibration factors are round numbers there and nonsense in file order.
This tool takes and writes files in DUMP order (what your programmer saves) and does all decoding in firmware order.
Byte numbers on the command line are FILE byte numbers; EEPROM_MAP.md lists both.

Integrity rule enforced by the balance at power-on (any failure -> ERROR):
    0x55 + sum(bytes) == 0 (mod 256)    for the blocks  4-7, 8-11 and 20-31

Commands:
    info FILE                      decode a dump, show checksum state and the closest known template
    verify FILE                    exit status 0 if all three sums are good
    fix IN OUT                     recompute the checksum bytes
    set IN OUT [options]           edit fields or raw bytes, then repair the checksums
    build --template NAME --out F  construct an image from a known template
    diff A B                       show differing bytes
    templates                      list the known templates
    from-words "0001 0080 ..."     convert 16 hex words (as printed in forum posts) to a binary file
    to-words FILE                  print a binary file as 16 hex words
Only the Python standard library is needed.
"""
import argparse
import json
import os
import sys

SIZE = 32
GOOD = 0xAB                         # sum of each checked block, mod 256
THRESHOLDS = (0x86, 0x89, 0xA3, 0xC2)   # ROM table 0x309, selected by firmware byte 20 bits 0-1
BANDS = (8, 4, 2, 12)                    # ROM table 0x3B7, selected by firmware byte 20 bits 2-3
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_JSON = os.path.join(HERE, 'templates.json')
DIGIT_UNITS = 8                          # internal units per display digit (X and the limit are 8 x digits)


# ----------------------------------------------------------------------------- byte order
def swap_pairs(d):
    """File (dump) order <-> firmware (RAM) order. It is its own inverse."""
    d = bytearray(d)
    for i in range(0, len(d) - 1, 2):
        d[i], d[i + 1] = d[i + 1], d[i]
    return bytes(d)


fw = swap_pairs


def fidx(i):
    """File index of firmware byte i (and vice versa)."""
    return i ^ 1


# ----------------------------------------------------------------------------- checks
def sums(d):
    return {'record 1 (bytes 4-7)': sum(d[4:8]) & 255,
            'record 2 (bytes 8-11)': sum(d[8:12]) & 255,
            'template (bytes 20-31)': sum(d[20:32]) & 255}


def valid(d):
    return all(v == GOOD for v in sums(d).values())


SWAP_MODE = 'auto'       # 'auto' | 'yes' | 'no' (set by the --swapped option)


def looks_firmware_order(raw):
    """Files saved by a programmer that already swaps the words have 80 00 where every dump has 00 80 (bytes 2-3)."""
    return raw[2:4] == b'\x80\x00'


def load(path):
    """Read a dump and return (data in dump order, was_swapped). `was_swapped` tells save() to write the file back
    in the order it came in."""
    with open(path, 'rb') as f:
        raw = f.read()
    if len(raw) != SIZE:
        raise SystemExit(f'{path}: expected {SIZE} bytes, got {len(raw)}')
    swapped = {'yes': True, 'no': False}.get(SWAP_MODE, looks_firmware_order(raw))
    return (swap_pairs(raw) if swapped else raw), swapped


def save(path, d, swapped=False):
    with open(path, 'wb') as f:
        f.write(swap_pairs(d) if swapped else bytes(d))


# ----------------------------------------------------------------------------- firmware-order accessors
def get24(r, i):
    """24-bit value, least significant byte first, at firmware index i."""
    return r[i] | (r[i + 1] << 8) | (r[i + 2] << 16)


def put24(r, i, v):
    if not 0 <= v <= 0xFFFFFF:
        raise ValueError('24-bit value out of range')
    r[i], r[i + 1], r[i + 2] = v & 255, (v >> 8) & 255, (v >> 16) & 255


REC = {1: 4, 2: 8}          # firmware index of a calibration record: 3 value bytes, then the checksum byte


def record(d, which):
    r = fw(d)
    i = REC[which]
    return get24(r, i), r[i + 3]


def modify(d, fn):
    """Apply fn to a bytearray in firmware order and return the result in dump order."""
    r = bytearray(fw(d))
    fn(r)
    return fw(bytes(r))


def set_record(d, which, value):
    i = REC[which]

    def f(r):
        put24(r, i, value)
        r[i + 3] = (GOOD - sum(r[i:i + 3])) & 255
    return modify(d, f)


def repair(d):
    """Recompute the three checksum bytes the way the firmware does: firmware bytes 7 and 11 for the records and 31
    (file byte 30) for the template. Everything else is left alone."""
    def f(r):
        r[7] = (GOOD - sum(r[4:7])) & 255
        r[11] = (GOOD - sum(r[8:11])) & 255
        r[31] = (GOOD - sum(r[20:31])) & 255
    return modify(d, f)


def fields(d):
    """Decoded parameters (from the firmware-order view)."""
    r = fw(d)
    limit = get24(r, 25)
    return {
        'unit_word': (r[2], r[3]),
        'record1': get24(r, 4), 'record2': get24(r, 8),
        'threshold_idx': r[20] & 3, 'band_idx': (r[20] >> 2) & 3, 'filter_row': (r[20] >> 4) & 3,
        'test_mode': bool(r[20] & 0x40), 'learn': bool(r[20] & 0x80),
        'code': r[21] & 7,
        'x': get24(r, 22), 'limit': limit & 0x7FFFFF, 'window_half': bool(r[27] & 0x80),
        'dd_option_off': (r[30] & 0x7F) == 0x7F and not (r[28] & 0x08),
        'dd_option_active': (r[30] & 0x7F) == 0x7F,
        'sd_off': (r[30] & 0x7F) == 0x7F and not (r[28] & 0x10),
        'auto_zero_off': (r[30] & 0x7F) == 0x7F and not (r[28] & 0x20),
        'fine_range_active': (r[30] & 0x7F) != 0x7F,
        'fine_range': r[28] | (r[29] << 8) | (r[30] << 16),
        'r28': r[28], 'r29': r[29], 'r30': r[30],
    }


# ----------------------------------------------------------------------------- templates library
def set_option_bit(r, bit, on):
    """File byte 29 (firmware byte 28) option bits: 3 DeltaDisplay, 4 stability detector (SD), 5 auto zero. Set = feature on.
    Arms the option byte by making the top byte of the DeltaRange limit 7F (the family default)."""
    if (r[30] & 0x7F) != 0x7F:
        r[30] = 0x7F
    r[28] = (r[28] | (1 << bit)) if on else (r[28] & ~(1 << bit) & 255)


def set_fine_range(r, digits):
    """DeltaRange limit: firmware bytes 28, 29, 30 hold a 24-bit value in 1/8-digit units, LSB first (r is in firmware order)."""
    units = digits * DIGIT_UNITS
    if not 0 < units < 0x7F0000:
        raise ValueError('fine range must be between 1 and %d digits' % (0x7F0000 // DIGIT_UNITS - 1))
    r[28], r[29], r[30] = units & 255, (units >> 8) & 255, units >> 16


def set_fine_range_off(r):
    if (r[30] & 0x7F) != 0x7F:                  # a fine-range value is stored: put the family default back (option byte F8 = DeltaDisplay on)
        r[28] = 0xF8
    r[29], r[30] = 0xFF, 0x7F


def load_templates():
    with open(TEMPLATES_JSON) as f:
        return json.load(f)['templates']


def template_bytes(t):
    return bytes.fromhex(t['bytes_2_3']), bytes.fromhex(t['bytes_20_31'])


def closest(d, n=3):
    """Known templates ranked by differing bytes (file bytes 2-3 and 20-29, 31; byte 30 is the checksum)."""
    out = []
    for t in load_templates():
        b23, b2031 = template_bytes(t)
        diff = [i for i in (2, 3) if d[i] != b23[i - 2]]
        diff += [i for i in range(20, 32) if i != 30 and d[i] != b2031[i - 20]]
        out.append((len(diff), t['name'], diff, t))
    out.sort(key=lambda x: x[0])
    return out[:n]


# ----------------------------------------------------------------------------- decoding
def describe(d):
    f = fields(d)
    L = []
    L.append('Checksums (each block must sum to 0xAB; checksum bytes are file bytes 6, 10 and 30):')
    for k, v in sums(d).items():
        L.append(f'  {k:24s} sum=0x{v:02X}  {"OK" if v == GOOD else "BAD"}')
    L.append('')
    L.append(f'Scratch (file bytes 1, 0): flag register 0x{d[1]:02X}, counter 0x{d[0]:02X} - saved on standby, not configuration')
    L.append(f'Unit word  (file bytes 3, 2): 0x{d[3]:02X}{d[2]:02X}   saved unit = {d[3] >> 4}  (8 = grams in every known dump)')
    r = fw(d)
    for w in (1, 2):
        v, c = record(d, w)
        L.append(f'Record {w}   : {v:>9d} (0x{v:06X}), checksum byte 0x{c:02X}   '
                 + ('<- live calibration factor, rewritten by the CAL routine' if w == 1 else '<- saved / factory value'))
    ratio = f['record1'] / f['record2'] if f['record2'] else 0
    L.append(f'             record 1 / record 2 = {ratio:.4f}')
    L.append('')
    L.append('Template:')
    L.append(f'  file byte 21 = 0x{d[21]:02X}: threshold index {f["threshold_idx"]} (0x{THRESHOLDS[f["threshold_idx"]]:02X}), '
             f'stability band index {f["band_idx"]} ({BANDS[f["band_idx"]]}), filter row {f["filter_row"]}, '
             f'TEST MODE {"ON (display x2)" if f["test_mode"] else "off"}, learn-X {"ON" if f["learn"] else "off"}')
    L.append(f'  file byte 20 = 0x{d[20]:02X}: code {f["code"]} - sets the decimal-point position with the saved unit; '
             f'DeltaDisplay is also off when (unit base + code) & 7 == 5 (grams: code 5, which removes the decimals)')
    x = f['x']
    L.append(f'  X (file bytes 23, 22, 25)    = {x} internal units = {x / DIGIT_UNITS:g} display digits   <- calibration weight')
    L.append(f'  limit (file bytes 24, 27, 26) = {f["limit"]} internal units = {f["limit"] / DIGIT_UNITS:g} display digits   <- range limit')
    L.append(f'  calibration window: |reading - X| < X/{2 if f["window_half"] else 32} '
             f'({"X/2" if f["window_half"] else "+-3.1 %"})')
    L.append(f'  DeltaDisplay option (file bytes 29 and 31 = 0x{d[29]:02X}, 0x{d[31]:02X}): '
             + ('active in this image, option bit set -> DeltaDisplay OFF' if f['dd_option_off'] else
                ('option armed (byte 31 = 7F) but bit 3 of byte 29 is set -> DeltaDisplay stays ON' if f['dd_option_active'] else
                 'not armed (byte 31 low 7 bits are not 7F)')))
    if not f['fine_range_active']:
        L.append(f'  option byte (file byte 29 = 0x{d[29]:02X}): DeltaDisplay {"OFF" if f["dd_option_off"] else "on"}, '
                 f'stability detector (SD) {"OFF" if f["sd_off"] else "on"}, auto zero {"OFF" if f["auto_zero_off"] else "on"}')
    if f['fine_range_active']:
        L.append(f'  DeltaRange: fine range up to {f["fine_range"] / DIGIT_UNITS:g} display digits (file bytes 29, 28, 31 as a 24-bit value, LSB first); '
                 'above it the last digit is blanked')
    else:
        L.append('  DeltaRange: not used (file byte 31 low 7 bits = 7F; byte 29 is then the option byte above)')
    L.append('')
    L.append('Closest known templates (file bytes 2-3, 20-29, 31):')
    for n, name, diff, t in closest(d):
        L.append(f'  {name:28s} {n} byte(s) differ' + (f' (file bytes {", ".join(map(str, diff))})' if diff else '  <- identical'))
    return '\n'.join(L)


# ----------------------------------------------------------------------------- commands
def cmd_info(a):
    d, sw = load(a.file)
    print(a.file + ('   (file was in firmware word order, turned around for display)' if sw else ''))
    print(describe(d))


def cmd_verify(a):
    d, sw = load(a.file)
    for k, v in sums(d).items():
        print(f'{k:24s} sum=0x{v:02X} {"OK" if v == GOOD else "BAD"}')
    sys.exit(0 if valid(d) else 2)


def report_change(old, new):
    ch = [i for i in range(SIZE) if old[i] != new[i]]
    print('changed file bytes:', ', '.join(f'{i}: {old[i]:02X}->{new[i]:02X}' for i in ch) if ch else 'none')


def cmd_fix(a):
    d, sw = load(a.input)
    new = repair(d)
    report_change(d, new)
    save(a.output, new, sw)
    print('wrote', a.output, '(valid)' if valid(new) else '(STILL INVALID)')


def cmd_set(a):
    d, sw = load(a.input)
    n = bytes(d)
    for spec in a.byte or []:
        k, v = spec.split('=')
        b = bytearray(n)
        b[int(k, 0)] = int(v, 0)
        n = bytes(b)

    def edit(fn):
        nonlocal n
        n = modify(n, fn)

    if a.test_mode:
        edit(lambda r: r.__setitem__(20, (r[20] | 0x40) if a.test_mode == 'on' else (r[20] & ~0x40 & 255)))
    if a.deltadisplay == 'off':
        def off(r):
            r[30] = 0x7F if (r[30] & 0x7F) != 0x7F else r[30]      # arm the option byte (already 7F in every known dump)
            r[28] &= ~0x08 & 255                                     # bit 3 clear = DeltaDisplay off
        edit(off)
    elif a.deltadisplay == 'on':
        edit(lambda r: r.__setitem__(28, r[28] | 0x08))
    if a.code is not None:
        if not 0 <= a.code <= 7:
            raise SystemExit('--code must be 0-7')
        edit(lambda r: r.__setitem__(21, (r[21] & ~7 & 255) | a.code))
    if a.rec1 is not None:
        n = set_record(n, 1, int(a.rec1, 0))
    if a.rec2 is not None:
        n = set_record(n, 2, int(a.rec2, 0))
    if a.x is not None:
        edit(lambda r: put24(r, 22, int(a.x, 0)))
    if a.x_digits is not None:
        edit(lambda r: put24(r, 22, int(a.x_digits) * DIGIT_UNITS))
    if a.limit is not None:
        edit(lambda r: put24(r, 25, int(a.limit, 0)))
    for opt, bit in ((a.sd, 4), (a.auto_zero, 5)):
        if opt:
            edit(lambda r, bit=bit, opt=opt: set_option_bit(r, bit, opt == 'on'))
    if a.fine_range == 'off':
        edit(set_fine_range_off)
    elif a.fine_range_digits is not None:
        edit(lambda r: set_fine_range(r, int(a.fine_range_digits)))
    new = n if a.no_repair else repair(n)
    report_change(d, new)
    if not (a.byte or a.test_mode or a.deltadisplay or a.code is not None or a.rec1 or a.rec2 or a.x or a.x_digits
            or a.limit or a.fine_range or a.fine_range_digits is not None or a.sd or a.auto_zero):
        print('nothing to change')
    if a.dry_run:
        print('dry run - nothing written')
        return
    save(a.output, new, sw)
    print('wrote', a.output, '(valid)' if valid(new) else '(INVALID - the balance will show ERROR)')
    print('NOTE: after programming a modified image, calibrate the balance with its calibration weight.')


def cmd_build(a):
    t = next((t for t in load_templates() if t['name'].lower() == a.template.lower()), None)
    if t is None:
        raise SystemExit('unknown template; run "templates" for the list')
    b23, b2031 = template_bytes(t)
    d = bytearray(SIZE)
    d[2:4] = b23
    d[20:32] = b2031
    d = bytes(d)
    if a.donor:
        donor, _ = load(a.donor)
        d = d[:4] + donor[4:12] + d[12:]
        recs = f'calibration records copied from {a.donor}'
    else:
        d = set_record(set_record(d, 1, 0), 2, 0)
        recs = 'calibration records ZERO (untested on hardware; use --donor with a dump of the same scale if you can)'
    d = repair(d)
    if not valid(d):
        raise SystemExit('internal error: built image is invalid')
    save(a.out, d)
    print(f'built {a.out} from template {t["name"]}; {recs}')
    print('NOTE: the balance must be calibrated after programming.')


def cmd_diff(a):
    x, _ = load(a.a)
    y, _ = load(a.b)
    ch = [i for i in range(SIZE) if x[i] != y[i]]
    print('identical' if not ch else '\n'.join(f'file byte {i:2d}: {x[i]:02X} -> {y[i]:02X}' for i in ch))


def cmd_templates(a):
    for t in load_templates():
        b23, b2031 = template_bytes(t)
        d = bytearray(SIZE)
        d[2:4], d[20:32] = b23, b2031
        f = fields(bytes(d))
        print(f'{t["name"]:12s} X={f["x"] / DIGIT_UNITS:>8g} digits  limit={f["limit"] / DIGIT_UNITS:>9g} digits  '
              f'file bytes 2-3 {t["bytes_2_3"]}  20-31 {t["bytes_20_31"]}  ({t["source"]})')
        if t.get('notes'):
            print('    ' + t['notes'])


def cmd_from_words(a):
    words = a.words.replace(',', ' ').split()
    if len(words) != 16 or any(len(w) != 4 for w in words):
        raise SystemExit('expected 16 words of 4 hex digits')
    d = bytes.fromhex(''.join(words))
    with open(a.out, 'wb') as f:
        f.write(d)
    print('wrote', a.out, '- valid' if valid(d) else '- checksums do not verify')


def cmd_to_words(a):
    d, _ = load(a.file)
    print(' '.join(f'{d[i]:02X}{d[i + 1]:02X}' for i in range(0, SIZE, 2)))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--swapped', choices=('auto', 'yes', 'no'), default='auto',
                   help='input files saved in firmware word order (bytes 2-3 read 80 00); auto = guess from that header')
    sp = p.add_subparsers(dest='cmd', required=True)
    s = sp.add_parser('info'); s.add_argument('file'); s.set_defaults(f=cmd_info)
    s = sp.add_parser('verify'); s.add_argument('file'); s.set_defaults(f=cmd_verify)
    s = sp.add_parser('fix'); s.add_argument('input'); s.add_argument('output'); s.set_defaults(f=cmd_fix)
    s = sp.add_parser('set'); s.add_argument('input'); s.add_argument('output')
    s.add_argument('--byte', action='append', metavar='N=VALUE', help='set a raw FILE byte (repeatable)')
    s.add_argument('--test-mode', choices=('on', 'off'), help='file byte 21 bit 6: display x2 service mode')
    s.add_argument('--deltadisplay', choices=('on', 'off'),
                   help='file byte 29 bit 3 (needs byte 31 = 7F): clear = DeltaDisplay off, decimal point unchanged')
    s.add_argument('--code', type=int, help='file byte 20 bits 0-2: moves the decimal point (see EEPROM_MAP.md)')
    s.add_argument('--rec1', help='24-bit value for calibration record 1')
    s.add_argument('--rec2', help='24-bit value for calibration record 2')
    s.add_argument('--x', help='calibration weight X in internal units')
    s.add_argument('--x-digits', type=int, help='calibration weight in display digits (X = 8 x digits)')
    s.add_argument('--limit', help='range limit in internal units')
    s.add_argument('--stability-detector', '--pilot', dest='sd', choices=('on', 'off'), help='file byte 29 bit 4: the stability detector (SD) pilot, a leftmost display segment that lights while the reading is unstable (needs byte 31 = 7F)')
    s.add_argument('--auto-zero', choices=('on', 'off'), help='file byte 29 bit 5: slow zero tracking near zero (needs byte 31 = 7F)')
    s.add_argument('--fine-range-digits', type=int, help='DeltaRange: fine range extent in display digits; above it the last digit is blanked (file bytes 29, 28, 31)')
    s.add_argument('--fine-range', choices=('off',), help='no DeltaRange (file byte 31 = 7F, byte 28 = FF): the PE3000/PE6000/PE16 default')
    s.add_argument('--no-repair', action='store_true', help='do not recompute the checksum bytes afterwards')
    s.add_argument('--dry-run', action='store_true'); s.set_defaults(f=cmd_set)
    s = sp.add_parser('build'); s.add_argument('--template', required=True); s.add_argument('--out', required=True)
    s.add_argument('--donor', help='dump whose calibration records (bytes 4-11) to copy'); s.set_defaults(f=cmd_build)
    s = sp.add_parser('diff'); s.add_argument('a'); s.add_argument('b'); s.set_defaults(f=cmd_diff)
    s = sp.add_parser('templates'); s.set_defaults(f=cmd_templates)
    s = sp.add_parser('from-words'); s.add_argument('words'); s.add_argument('--out', required=True); s.set_defaults(f=cmd_from_words)
    s = sp.add_parser('to-words'); s.add_argument('file'); s.set_defaults(f=cmd_to_words)
    a = p.parse_args(argv)
    global SWAP_MODE
    SWAP_MODE = a.swapped
    a.f(a)


if __name__ == '__main__':
    main()
