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

## Display update speed - not an EEPROM setting

Ramp inputs (fast: 1 count per 1500 cycles, slow: 1 count per 60000 cycles) on the PE6000 image, all 16 combinations of filter row and stability band (file byte 21 bits 2-5):

* **Update rate:** 38 display changes in 3 M cycles (about 5 per second nominal, ~4 per second on the real 4.915 MHz crystal) for every variant. It is fixed by the ROM:
  the interrupt routine counts 30 processing passes (the constant at ROM 0x1CE) before it signals a new reading.
* **Lag behind the input:** filter rows 0, 1 and 2 are identical; row 3 lags about 35 % more. No band or threshold value changes it.
  The rows differ only in the filter table at ROM 0x396 (indexed by the stability counter), where rows 0-2 share the unstable-state entries.
* **A ROM patch would change it** (not possible on the mask-ROM part, emulator only): setting the constant at 0x1CE to 0x0F gives 74 updates, to 0x0A gives 109 - the update rate is simply proportional to 1/passes.
  Fewer passes per reading means less averaging and so a noisier last digit, which the adaptive filter only partly hides.

## Option byte bits 4 and 5 (file byte 29)

* Bit 4 clear: the leftmost display segment (bit 3 of the first display byte, `89` vs `81`) never lights while the reading is moving - the stability-detector (SD) pilot of the manuals.
* Bit 5 clear: the zero-tracking branch at ROM 0x6B4-0x6CF is never executed (203 passes with the bit set, 0 with it clear). With noise, the zero reference RAM 0x51 is stepped back by one unit
  per pass when the bit is set and stays where it drifted when it is clear; at the displayed resolution the readings were the same. This is the auto zero.

* Bits 0-2, 6, 7 of file byte 29: F9, FA, FC, B8, 78 and FF run exactly the same code path as F8 and give identical display frames (400 of 400); only RAM 0x3C, 0x3F and 0xD5 differ. They are unused.

## File bytes 12-19

Setting each of them to FF and to 55 (checksums unchanged, they are not covered): same instructions executed, 400 of 400 identical display frames; only the matching RAM 0x2C-0x33 differs. The firmware
never reads them as parameters; they are written only by the interface commands R and U. See docs/FIRMWARE.md.

## File byte 28

With byte 31 = 7F, twelve values (FF, 00, single bits, 53, 7F) give identical displays. With a DeltaRange limit (byte 29 = 00, byte 31 = 00), byte 28 is the middle byte: 07 (224 digits), 0B (352) blank the last digit of a 356-digit reading;
0D (416), 0E (448), 1F (992) do not, but still blank a 1067-digit reading; 2F (1504), 4F, 8F do not blank either. Each bit adds 32 x 2^bit digits.

## Every remaining byte, every bit (file bytes 0-3 and 20-27)

Each bit flipped in turn on the PE6000 image, noisy rest + two load steps + unloading; executed-PC set, display frames and RAM compared with the unmodified image. Summary in EEPROM_MAP.md ("Byte-by-byte check").
Results worth recording: byte 0 bits 6-7 delay the first display after power-on (hold-off counter, recovers by itself); byte 1 and byte 2 have no effect; byte 3's high nibble is the unit, bit 3 adds a symbol;
byte 20 bits 3-7 and byte 21 bit 7 (outside calibration) have no effect; X (bytes 22, 23, 25) and the limit's low bytes (24, 27) do not change the weighing display;
**byte 26 bits 3-6 change the executed code in 88 places and 86 of 200 frames** - the limit's top byte reaching 13 (limit >= 106496 digits) switches to a different display-processing path (ROM 0xB6A).

## Fastmode - no EEPROM lever found

The service bulletin ME-701763 ties the faster Fastmode to the ME-47455 processor and its own bar-code table. Nothing in the EEPROM, tried one byte
at a time, produces a markedly faster settling than the PE6000/PE16 values; the DeltaDisplay half of Fastmode is the byte 29 bit 3 option.
Combinations of two bytes and the real counter hardware are not modelled, so a lever could still hide there.
