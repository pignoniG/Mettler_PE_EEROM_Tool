# Emulator results

**Correction.** An earlier version of this file used firmware byte numbers as if they were dump-file numbers (see EEPROM_MAP.md section 0)
and so drew some wrong conclusions. Everything below is redone with **file byte numbers**, dumps loaded in file order, base image
`examples/pe6000_own.bin`, a normal power-on (`Scale.power_on()`: standby, then the ON event), a steady count, then a noisy load step.
Time figures are nominal; only comparisons between variants mean anything.

## DeltaDisplay - solved, confirmed on hardware

| change (file bytes) | last digit blank in the emulator | notes |
|---|---|---|
| none (PE6000 as shipped) | 8 % of frames | |
| byte 29 F8 -> F0 (byte 31 = 7F) | 0 % | **real PE6000: display no longer blanks**; nothing else changes |
| byte 29 -> 00 | 0 % | same effect |
| byte 20 = 05 (decimal-point code 5) | 0 % | also moves the decimal point to the last digit (5.3 -> 53) |
| byte 21 changed (threshold/band bits) | still blanks, sensitivity differs | matches the real chip flashed with the wrong byte: blanking "less sensitive, still there" |
| byte 31 = FF | blanks on every frame | bit 7 of the gate byte inverts the effect; do not use |

## Decimal-point code (file byte 20 bits 0-2) does not change resolution

PE6000 image, only byte 20 bits 0-2 changed (checksum repaired), normal power-on, same load step (+60 counts), run with no noise and with 0.3 counts of
Gaussian noise per integration cycle. The settled display is the same digit string for every code; only the decimal point moves:

| code | display |
|---|---|
| 0 | 0.01067 |
| 1 | 0.1067 |
| 2 | 1.067 |
| 3 | 10.67 |
| 4 | 106.7 |
| 5 | 1067 |
| 6, 7 | `Error` |

The last digit is the same physical step in every case and the noisy runs show no extra flicker, so the code gives no extra resolution: it relabels the scale by powers of ten,
so only the code the balance was built with shows the true weight. Tested only with the unit stored in this image (grams); other units use a different base.
Emulator only, not tried on a real balance.

## Test mode, calibration weight

* File byte 21 bit 6 doubles the displayed value (1067 -> 2134 for the same input): the service manual's service mode.
* File bytes 23, 22, 25 are the calibration weight X in units of 1/8 digit; see EEPROM_MAP.md.

## Every other single-byte change, file bytes 12-31 (all bit flips + 00 + FF, 2 noise seeds)

Metrics: displayed value, time until the stability counter drops, time until it is stable again, convergence, rest flicker, blank fraction.

* **No byte in 12-19 does anything** in this model (the loader staging area, unused by the weighing path).
* Bytes 22-25, 27-28: no effect on settling or display (the weight/limit bytes matter for calibration and overload, not modelled by the sweep).
* File byte 26 (limit, high part): changing low bits slightly raises the blank fraction (0.08 -> 0.13), no other effect.
* **File byte 21 selectors, all 64 combinations of bits 0-5:** threshold index 0-2: no effect on settling; **index 3 (0xC2): the display becomes unreadable in the emulator -
  avoid**. Stability band: 12 (index 3, PE6000 default) and 8 (index 0) settle in 2031 ms; 4 (index 1) 2031-2098 ms; 2 (index 2) 2264 ms - a stricter band is slower.
  Filter row 3 gives a slightly earlier stable flag (1998 ms) but a slower convergence (1166 ms vs 966 ms to within 100 digits). The differences are 5-50 %, not the
  step change that "faster weighing-in" would need.

## Fastmode - no EEPROM lever found

The service bulletin ME-701763 ties the faster Fastmode to the ME-47455 processor and its own bar-code table. Nothing in the EEPROM, tried one byte
at a time, produces a markedly faster settling than the PE6000/PE16 values; the DeltaDisplay half of Fastmode is the byte 29 bit 3 option.
Combinations of two bytes and the real counter hardware are not modelled, so a lever could still hide there.
