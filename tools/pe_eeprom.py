#!/usr/bin/env python3
"""pe_eeprom - decode, verify, edit and rebuild the 32-byte parameter EEPROM (MCM2801 EAROM) of Mettler PE balances.

The format was read out of the CPU firmware (ME-47455 V4.1, INS8050); see EEPROM_MAP.md for the evidence.
Integrity rule enforced by the balance at power-on (any failure -> ERROR):

    0x55 + sum(bytes) == 0  (mod 256)   for   bytes 4-7, bytes 8-11 and bytes 20-31

Commands:
    info FILE                      decode a dump, show checksum state and the closest known template
    verify FILE                    exit status 0 if all three sums are good
    fix IN OUT [--adjust 30|31]    recompute the checksum bytes (7, 11 and 30 or 31)
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
GOOD = 0xAB                       # sum of each checked block, mod 256
REC = {1: 4, 2: 8}                # start of calibration record 1 / 2 (3 value bytes + 1 checksum byte)
TEMPLATE = (20, 32)
THRESHOLDS = (0x86, 0x89, 0xA3, 0xC2)   # ROM table 0x309, selected by byte 20 bits 0-1
BANDS = (8, 4, 2, 12)                    # ROM table 0x3B7, selected by byte 20 bits 2-3
DELTADISPLAY_OFF_CODE = 5                # byte 21 bits 0-2
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_JSON = os.path.join(HERE, 'templates.json')


# ----------------------------------------------------------------------------- basic image handling
def swap_pairs(d):
    d = bytearray(d)
    for i in range(0, len(d) - 1, 2):
        d[i], d[i + 1] = d[i + 1], d[i]
    return bytes(d)


def sums(d):
    return {'record 1 (bytes 4-7)': sum(d[4:8]) & 255,
            'record 2 (bytes 8-11)': sum(d[8:12]) & 255,
            'template (bytes 20-31)': sum(d[20:32]) & 255}


def valid(d):
    return all(v == GOOD for v in sums(d).values())


SWAP_MODE = 'auto'       # 'auto' | 'yes' | 'no' (set by the --swapped option)


def looks_swapped(raw):
    """Swapping the two bytes of every word does NOT change the checksums (the checked blocks are pair-aligned),
    so it cannot be detected that way. All known dumps have 00 80 in bytes 2-3, which swapped reads 80 00."""
    return raw[2:4] == b'\x80\x00'


def load(path):
    """Read a dump. Returns (data, swapped). Some programmers save each 16-bit word byte-swapped; 'swapped' tells
    save() to write the file back in the same order it came in."""
    with open(path, 'rb') as f:
        raw = f.read()
    if len(raw) != SIZE:
        raise SystemExit(f'{path}: expected {SIZE} bytes, got {len(raw)}')
    swapped = {'yes': True, 'no': False}.get(SWAP_MODE, looks_swapped(raw))
    return (swap_pairs(raw) if swapped else raw), swapped


def save(path, d, swapped=False):
    with open(path, 'wb') as f:
        f.write(swap_pairs(d) if swapped else bytes(d))


def get24(d, i):
    return d[i] | (d[i + 1] << 8) | (d[i + 2] << 16)


def put24(d, i, v):
    if not 0 <= v <= 0xFFFFFF:
        raise ValueError('24-bit value out of range')
    d[i], d[i + 1], d[i + 2] = v & 255, (v >> 8) & 255, (v >> 16) & 255


def set_record(d, which, value):
    i = REC[which]
    put24(d, i, value)
    d[i + 3] = (GOOD - sum(d[i:i + 3])) & 255


def repair(d, adjust=30, records=True):
    """Return a copy with the checksum bytes recomputed: bytes 7 and 11, and byte `adjust` (30 or 31)."""
    if adjust not in (30, 31):
        raise ValueError('adjust must be 30 or 31')
    d = bytearray(d)
    if records:
        for w in (1, 2):
            i = REC[w]
            d[i + 3] = (GOOD - sum(d[i:i + 3])) & 255
    d[adjust] = (d[adjust] + GOOD - sum(d[20:32])) & 255
    return bytes(d)


# ----------------------------------------------------------------------------- templates library
def load_templates():
    with open(TEMPLATES_JSON) as f:
        return json.load(f)['templates']


def template_bytes(t):
    return bytes.fromhex(t['bytes_2_3']), bytes.fromhex(t['bytes_20_31'])


def closest(d, n=3):
    """Known templates ranked by the number of differing bytes in 2-3 and 20-29 (30/31 are checksum bytes)."""
    out = []
    for t in load_templates():
        b23, b2031 = template_bytes(t)
        diff = [i for i in (2, 3) if d[i] != b23[i - 2]]
        diff += [i for i in range(20, 30) if d[i] != b2031[i - 20]]
        out.append((len(diff), t['name'], diff, t))
    out.sort(key=lambda x: x[0])
    return out[:n]


# ----------------------------------------------------------------------------- decoding
def describe(d):
    L = []
    s = sums(d)
    L.append('Checksums (each block must sum to 0xAB):')
    for k, v in s.items():
        L.append(f'  {k:24s} sum=0x{v:02X}  {"OK" if v == GOOD else "BAD"}')
    L.append('')
    L.append(f'Bytes 0-1  : {d[0]:02X} {d[1]:02X}   scratch (flag register / counter saved on standby; not configuration)')
    L.append(f'Bytes 2-3  : {d[2]:02X} {d[3]:02X}   byte 2 high nibble = saved unit index (user setting)')
    for w in (1, 2):
        i = REC[w]
        L.append(f'Record {w}   : value 0x{get24(d, i):06X} ({get24(d, i):>8d}) checksum byte 0x{d[i + 3]:02X}'
                 + ('   <- live calibration factor, rewritten by the CAL routine' if w == 1 else '   <- saved / fallback copy'))
    b20, b21 = d[20], d[21]
    L.append('')
    L.append('Template (bytes 20-31):')
    L.append(f'  byte 20 = 0x{b20:02X}: threshold index {b20 & 3} (0x{THRESHOLDS[b20 & 3]:02X}), '
             f'stability band index {(b20 >> 2) & 3} ({BANDS[(b20 >> 2) & 3]}), filter row {(b20 >> 4) & 3}, '
             f'TEST MODE {"ON (display x2)" if b20 & 0x40 else "off"}, learn-X-on-calibration {"ON" if b20 & 0x80 else "off"}')
    code = b21 & 7
    L.append(f'  byte 21 = 0x{b21:02X}: resolution code {code}, DeltaDisplay '
             + ('DISABLED (code 5)' if code == DELTADISPLAY_OFF_CODE else 'enabled (last digit blanks while the reading is unstable)'))
    L.append(f'  bytes 22-24 = {d[22]:02X} {d[23]:02X} {d[24]:02X}: 24-bit constant X = {get24(d, 22)} (calibration window centre / factor)')
    L.append(f'  bytes 25-27 = {d[25]:02X} {d[26]:02X} {d[27]:02X}: 24-bit threshold {get24(d, 25)}; byte 27 bit 7 = {(d[27] >> 7) & 1} '
             f'-> calibration window X/{2 if d[27] & 0x80 else 32}; low 7 bits {d[27] & 0x7F} (compared with 13)')
    L.append(f'  bytes 28-29 = {d[28]:02X} {d[29]:02X}   byte 30 = {d[30]:02X}   byte 31 = {d[31]:02X} (checksum / adjust bytes)')
    L.append('')
    L.append('Closest known templates (bytes 2-3 and 20-29):')
    for n, name, diff, t in closest(d):
        L.append(f'  {name:28s} {n} byte(s) differ' + (f' (bytes {", ".join(map(str, diff))})' if diff else '  <- identical'))
    return '\n'.join(L)


# ----------------------------------------------------------------------------- commands
def cmd_info(a):
    d, sw = load(a.file)
    print(a.file + ('   (word-swapped file, turned around for display)' if sw else ''))
    print(describe(d))


def cmd_verify(a):
    d, sw = load(a.file)
    for k, v in sums(d).items():
        print(f'{k:24s} sum=0x{v:02X} {"OK" if v == GOOD else "BAD"}')
    sys.exit(0 if valid(d) else 2)


def report_change(old, new):
    ch = [i for i in range(SIZE) if old[i] != new[i]]
    print('changed bytes:', ', '.join(f'{i}: {old[i]:02X}->{new[i]:02X}' for i in ch) if ch else 'none')


def cmd_fix(a):
    d, sw = load(a.input)
    new = repair(d, a.adjust)
    report_change(d, new)
    save(a.output, new, sw)
    print('wrote', a.output, '(valid)' if valid(new) else '(STILL INVALID)')


def cmd_set(a):
    d, sw = load(a.input)
    n = bytearray(d)
    for spec in a.byte or []:
        k, v = spec.split('=')
        n[int(k, 0)] = int(v, 0)
    if a.test_mode:
        n[20] = (n[20] | 0x40) if a.test_mode == 'on' else (n[20] & ~0x40 & 255)
    if a.deltadisplay == 'off':
        n[21] = (n[21] & ~7 & 255) | DELTADISPLAY_OFF_CODE
    elif a.deltadisplay == 'on':
        if a.code is None or not 0 <= a.code <= 7 or a.code == DELTADISPLAY_OFF_CODE:
            raise SystemExit('--deltadisplay on needs --code N (0-7, not 5). The code also selects the base resolution '
                             'constant, so use the value of a balance with the display you want (PE16/PE360: 1, '
                             'PE1600: 0, PE6000: 4). See EEPROM_MAP.md.')
        n[21] = (n[21] & ~7 & 255) | a.code
    if a.rec1 is not None:
        set_record(n, 1, int(a.rec1, 0))
    if a.rec2 is not None:
        set_record(n, 2, int(a.rec2, 0))
    new = repair(n, a.adjust, records=True)
    report_change(d, new)
    if not (a.byte or a.test_mode or a.deltadisplay or a.rec1 or a.rec2):
        print('nothing to change')
    if a.dry_run:
        print('dry run - nothing written')
        return
    save(a.output, new, sw)
    print('wrote', a.output, '(valid)' if valid(new) else '(STILL INVALID)')
    print('NOTE: after programming a modified image, calibrate the balance with its calibration weight.')


def cmd_build(a):
    t = next((t for t in load_templates() if t['name'].lower() == a.template.lower()), None)
    if t is None:
        raise SystemExit('unknown template; run "templates" for the list')
    b23, b2031 = template_bytes(t)
    d = bytearray(SIZE)
    d[2:4] = b23
    d[20:32] = b2031
    if a.donor:
        donor, _ = load(a.donor)
        d[4:12] = donor[4:12]
        recs = f'calibration records copied from {a.donor}'
    else:
        set_record(d, 1, 0)
        set_record(d, 2, 0)
        recs = 'calibration records ZERO (untested on hardware; use --donor with a dump of the same scale if you can)'
    d = bytearray(repair(d, 30))
    if not valid(d):
        raise SystemExit('internal error: built image is invalid')
    save(a.out, d)
    print(f'built {a.out} from template {t["name"]}; {recs}')
    print('NOTE: the balance must be calibrated after programming.')


def cmd_diff(a):
    x, _ = load(a.a)
    y, _ = load(a.b)
    ch = [i for i in range(SIZE) if x[i] != y[i]]
    print('identical' if not ch else '\n'.join(f'byte {i:2d}: {x[i]:02X} -> {y[i]:02X}' for i in ch))


def cmd_templates(a):
    for t in load_templates():
        print(f'{t["name"]:24s} bytes 2-3 {t["bytes_2_3"]}  bytes 20-31 {t["bytes_20_31"]}  ({t["source"]})')
        if t.get('notes'):
            print('    ' + t['notes'])


def cmd_from_words(a):
    words = a.words.replace(',', ' ').split()
    if len(words) != 16 or any(len(w) != 4 for w in words):
        raise SystemExit('expected 16 words of 4 hex digits')
    d = bytes.fromhex(''.join(words))
    with open(a.out, 'wb') as f:
        f.write(d)
    print('wrote', a.out, '- valid' if valid(d) else '- checksums do not verify (wrong word order?)')


def cmd_to_words(a):
    d, _ = load(a.file)
    print(' '.join(f'{d[i]:02X}{d[i + 1]:02X}' for i in range(0, SIZE, 2)))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--swapped', choices=('auto', 'yes', 'no'), default='auto',
                   help='byte order of input files: some programmers swap the two bytes of every word '
                        '(auto = guess from the 00 80 header)')
    sp = p.add_subparsers(dest='cmd', required=True)
    s = sp.add_parser('info'); s.add_argument('file'); s.set_defaults(f=cmd_info)
    s = sp.add_parser('verify'); s.add_argument('file'); s.set_defaults(f=cmd_verify)
    s = sp.add_parser('fix'); s.add_argument('input'); s.add_argument('output')
    s.add_argument('--adjust', type=int, choices=(30, 31), default=30); s.set_defaults(f=cmd_fix)
    s = sp.add_parser('set'); s.add_argument('input'); s.add_argument('output')
    s.add_argument('--byte', action='append', metavar='N=VALUE', help='set a raw byte (repeatable)')
    s.add_argument('--test-mode', choices=('on', 'off'), help='byte 20 bit 6: display x2 service mode')
    s.add_argument('--deltadisplay', choices=('on', 'off'), help='byte 21 bits 0-2 == 5 disables it')
    s.add_argument('--code', type=int, help='resolution code (0-7) for --deltadisplay on')
    s.add_argument('--rec1', help='24-bit value for calibration record 1')
    s.add_argument('--rec2', help='24-bit value for calibration record 2')
    s.add_argument('--adjust', type=int, choices=(30, 31), default=30)
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
