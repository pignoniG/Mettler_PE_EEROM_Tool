#!/usr/bin/env python3
"""Sweep EAROM template bytes in the emulator with a noisy load step and report how each change alters behaviour.

  python3 sweep.py [first_byte last_byte] [--seeds N]

Metrics per variant (median over noise seeds):
  gain      final displayed value for the same load (scale / resolution changes show up here)
  t_unst    ms after the step until the stability counter (RAM 0x8D) falls below 0x20
  t_stable  ms after the step until it is back at 0x7F ("stable")
  t100      ms until the display stays within 100 digits of its final value
  flicker   display changes per second at rest, before the load
  blank     fraction of display frames with the last digit blank
Failures (crash, no main loop, unreadable display) are reported as such.
"""
import sys, os, math, random, statistics, multiprocessing as mp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
from emu48 import Scale
from pe_eeprom import repair

# The CPU firmware is Mettler's and is not distributed: dump your own (docs/DUMPING_THE_CPU.md) into research/rom/
ROM = os.path.join(HERE, 'rom', 'ME-47455_INS8050.bin')
with open(os.path.join(HERE, '..', 'examples', 'pe3000_B_french_original.bin'), 'rb') as _f:
    BASE = _f.read()
DIG = {0x3F: 0, 0x06: 1, 0x5B: 2, 0x4F: 3, 0x66: 4, 0x6D: 5, 0x7D: 6, 0x07: 7, 0x7F: 8, 0x6F: 9, 0x00: 0}
MS = 2.5e-3          # ms per machine cycle


def value(raw):
    v = 0
    for b in raw[2:8]:
        k = b & 0x7F
        if k not in DIG:
            return None
        v = v * 10 + DIG[k]
    return v


def make(edits):
    d = bytearray(BASE)
    for k, v in edits.items():
        d[k] = v
    return bytes(repair(d, 30))


def run_one(args):
    edits, seed = args
    try:
        img = make(edits)
        rnd = random.Random(seed)
        st = {'t0': None}
        SIGMA, DELTA, TAU = 0.3, 60, 100_000

        def counts(cyc):
            base = 2000
            if st['t0'] is not None:
                base += DELTA * (1 - math.exp(-(cyc - st['t0']) / TAU))
            return round(base + rnd.gauss(0, SIGMA))

        s = Scale(ROM, img, count_fn=counts)
        c = s.cpu
        c.ext_p1 = 0xFE
        s.run_cycles(2_500_000)
        c.ext_p1 = 0xFF
        s.run_cycles(4_000_000)
        ok = False
        for _ in range(60):
            s.run_cycles(100_000)
            if c.ram[0x8D] == 0x7F and value(s.display_raw()) is not None:
                ok = True
                break
        if not ok:
            return {'fail': 'no stable zero (display=%r, 8D=%02X)' % (s.display(), c.ram[0x8D])}
        # rest period: count display changes and blank frames
        rest_changes, frames, blank, last = 0, 0, 0, None
        t_rest0 = c.cycles
        while c.cycles < t_rest0 + 2_000_000:
            s.run_cycles(13320)
            raw = s.display_raw()
            frames += 1
            if raw[7] == 0 and any(raw[2:7]):
                blank += 1
            if raw != last:
                rest_changes += 1
                last = raw
        flicker = rest_changes / ((c.cycles - t_rest0) * MS / 1000)
        # load step
        st['t0'] = c.cycles
        t_unst = t_stable = None
        series = []
        while c.cycles < st['t0'] + 5_000_000:
            s.run_cycles(13320)
            raw = s.display_raw()
            frames += 1
            if raw[7] == 0 and any(raw[2:7]):
                blank += 1
            v8d = c.ram[0x8D]
            t = (c.cycles - st['t0']) * MS
            if t_unst is None and v8d < 0x20:
                t_unst = t
            if t_unst is not None and t_stable is None and v8d == 0x7F:
                t_stable = t
            val = value(raw)
            if val is not None:
                series.append((t, val))
        if not series:
            return {'fail': 'display unreadable after load'}
        final = series[-1][1]
        t100 = None
        for t, v in series:
            if abs(v - final) <= 100:
                if t100 is None:
                    t100 = t
            else:
                t100 = None
        return {'gain': final, 't_unst': t_unst, 't_stable': t_stable, 't100': t100,
                'flicker': flicker, 'blank': blank / frames}
    except Exception as e:                                   # noqa
        return {'fail': 'crash: %s' % e}


def med(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def summarise(results):
    fails = [r['fail'] for r in results if 'fail' in r]
    good = [r for r in results if 'fail' not in r]
    if not good:
        return {'fail': fails[0]}
    return {k: med([r[k] for r in good]) for k in ('gain', 't_unst', 't_stable', 't100', 'flicker', 'blank')}


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    first, last = (int(args[0]), int(args[1])) if len(args) >= 2 else (23, 29)
    seeds = 3
    for i, a in enumerate(sys.argv):
        if a == '--seeds':
            seeds = int(sys.argv[i + 1])
    variants = [('baseline', {})]
    for b in range(first, last + 1):
        orig = BASE[b]
        vals = []
        for bit in range(8):
            vals.append(orig ^ (1 << bit))
        vals += [0x00, 0xFF]
        seen = set()
        for v in vals:
            if v in seen or v == orig:
                continue
            seen.add(v)
            variants.append((f'byte{b}=0x{v:02X} (was 0x{orig:02X})', {b: v}))
    jobs = [(e, 1000 + s) for _, e in variants for s in range(seeds)]
    print(f'{len(variants)} variants x {seeds} seeds = {len(jobs)} runs on {mp.cpu_count()} cores', flush=True)
    with mp.Pool(mp.cpu_count() - 1) as pool:
        out = pool.map(run_one, jobs, chunksize=1)
    table = []
    for i, (name, e) in enumerate(variants):
        table.append((name, summarise(out[i * seeds:(i + 1) * seeds])))
    base = table[0][1]
    print()
    print(f"{'variant':32s} {'gain':>8s} {'t_unst':>7s} {'t_stable':>8s} {'t100':>7s} {'flick/s':>8s} {'blank':>6s}")
    f = lambda x, w, p=0: ' ' * (w - 1) + '-' if x is None else f'{x:{w}.{p}f}'
    for name, r in table:
        if 'fail' in r:
            print(f'{name:32s} FAIL: {r["fail"]}')
            continue
        diff = ''
        if r is not base and 'fail' not in base:
            marks = []
            if base['gain'] and abs(r['gain'] - base['gain']) > 0.02 * base['gain']: marks.append('GAIN')
            if r['t_stable'] is not None and base['t_stable'] is not None and abs(r['t_stable'] - base['t_stable']) > 150: marks.append('STABLE')
            if r['t100'] is not None and base['t100'] is not None and abs(r['t100'] - base['t100']) > 300: marks.append('CONV')
            if abs(r['flicker'] - base['flicker']) > 0.5 * max(base['flicker'], 1): marks.append('FLICK')
            if abs(r['blank'] - base['blank']) > 0.02: marks.append('BLANK')
            diff = '  <-- ' + ','.join(marks) if marks else ''
        print(f"{name:32s} {f(r['gain'],8)} {f(r['t_unst'],7)} {f(r['t_stable'],8)} {f(r['t100'],7)} {f(r['flicker'],8,1)} {r['blank']:6.2f}{diff}")
