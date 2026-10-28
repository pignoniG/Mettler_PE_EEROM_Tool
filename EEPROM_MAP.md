# Mettler PE series - MCM2801 parameter EEPROM

Reverse-engineered from the CPU firmware **ME-47455 V4.1** (National INS8050-6LPX, a mask-ROM MCS-48 part, "20-02-83")
and checked against nine EEPROM dumps (five from the author's scales, four from a 2006 forum post).

Confidence tags: **[rom]** read from the firmware code; **[data]** holds in all nine dumps; **[hw]** reproduced on a real
balance; **[emu]** observed in the emulator in `research/`; **[guess]** inference.

## 0. Two byte numberings - read this first

The firmware reads each 16-bit EAROM word **low byte first**, so the byte the firmware calls *RAM 0x20+n* is **not** byte *n*
of a dump file: **file byte *i* = firmware byte *(i XOR 1)***. Pairs (0,1), (2,3), (4,5) ... are swapped.
The block checksums are blind to this (pair-aligned blocks), which is why it went unnoticed at first.

**This document uses FILE byte numbers (the offset in a dump made with the usual programmers, and in the forum word listings)
and gives the firmware byte in brackets where it matters.** The tools use file numbers everywhere (`--byte N=V`, the GUI grid).

An earlier version of this repository used firmware numbering as if it were file numbering. It was wrong; one DeltaDisplay recipe
based on it did not work on a real PE6000 (see section 4).

Some programmers save each word byte-swapped *again*; that file reads `80 00` instead of `00 80` at bytes 2-3 and is detected
from the header (override with `--swapped yes|no`).

## 1. Integrity rule  [rom] [data] [hw]

At power-on the firmware computes `0x55 + sum(bytes)` mod 256 over three blocks and requires 0, i.e. **each block sums to 0xAB**:

| block (file bytes) | checksum byte (file) | if it fails |
|---|---|---|
| 4-7 calibration record 1 | **6** | falls back to record 2 and rewrites record 1 |
| 8-11 calibration record 2 | **10** | if both bad: `ERROR` |
| 20-31 template | **30** | `ERROR` |

Verified: a French PE3000 image edited without fixing the template sum made the balance stop with an error; with the checksum byte repaired
it was accepted. The tool changes **only** the checksum byte of the block you touched.

## 2. Map (file byte; firmware byte in brackets)

| file byte | content |
|---|---|
| 0 [1] | scratch: down-counter saved on standby (00, 01, D0 seen). Not configuration **[rom][hw]** |
| 1 [0] | scratch: firmware flag register saved on standby **[rom]** |
| 2 [3] | `80` in all dumps: low half of the unit word |
| 3 [2] | **high nibble = the unit the user last selected** (index into a unit table; 8 = grams). A user setting **[rom]** |
| 4, 5, 7 [5,4,7] | **calibration record 1**, 24-bit, LSB first = file bytes 5, 4, 7: the live calibration factor (rewritten by CAL) **[rom][hw]** |
| 6 [7] | checksum of record 1 |
| 8, 9, 11 | calibration record 2: saved / factory copy (round numbers), within ~0.5 % of record 1; restored by `SUB_F03` **[rom]** |
| 10 | checksum of record 2 |
| 12-19 | zero in all dumps, not used by the paths read |
| 20 [21] | bits 0-2: **decimal-point code** - position class of the decimal point, combined with the unit. For grams: 1 = 3 decimals ... 4 = one decimal, **5 = integer** (and disables DeltaDisplay, see 4), 6/7 = `Error` **[rom][emu]** |
| 21 [20] | bits 0-1 **threshold** index {0x86,0x89,0xA3,0xC2} in the integration interrupt (a response/filter parameter); bits 2-3 **stability band** {8,4,2,12}; bits 4-5 **filter row** (table at 0x396); **bit 6 TEST MODE: display x2** (service manual "doubles values to facilitate adjustments"); bit 7 calibration copies the measured value into X **[rom][emu]** |
| 23, 22, 25 [22,23,24] | **X = calibration weight** in internal units, 24-bit LSB first, **1 unit = 1/8 of a display digit**. PE3000-A 80000 = 10000 digits = 1 kg at 0.1 g; PE3000-B 240000 = 30000 digits = 3 kg; PE6000 160000 = 2 kg; PE16 4 kg. Calibration is accepted if the measured value is within X/32 (+-3.1 %) of X **[rom][hw]** |
| 24, 27, 26 [25,26,27] | **range limit** (overload) in the same units ~ capacity + 3 %. **Bit 7 of file byte 26 = calibration window X/2 instead of X/32** **[rom]** |
| 28 [29] | unknown, FF in all dumps |
| 29 [28] | `F8` in the PE11..PE6000 family. **Bit 3 = DeltaDisplay option bit** (4) |
| 30 [31] | template checksum |
| 31 [30] | option gate: `7F` in all PE11..PE6000 dumps. If its low 7 bits are 7F, byte 29 is read as an option byte (RAM 0xD5 = ~byte 29) **[rom]** |

(LSB first, listed in that order. Use `pe_eeprom.py info` instead of decoding by hand.)

## 3. Normal / Certification mode, 1 kg vs 3 kg

* **The certification lock is a hardware jumper, not an EEPROM bit.** The service manual (155453037-PE-SM, sections 2.3 and the fault table) says that in a
  certified balance calibration (and unit selection) "can be blocked by setting a short-circuit plug on **ST4**" of the balance P/C board. The firmware agrees:
  the calibration routine (0x905) and the unit-selection path (0xE87) both start by reading port P1 bit 2 and bail out when it is low **[rom]** - ST4 very
  probably pulls P1.2 to ground (inferred from the code; trace it on your board). So an EEPROM edit can neither lock nor unlock calibration; remove or fit ST4.
* **Normal vs Certification mode "is simply the calibration weight"** (service manual): a practical weight in Normal mode, the certification-standard weight in
  Certification mode. That is the X field above. Reading a bar code also cancels the stored calibration factor, and each mode has its own bar-code set.
* Earlier text: no "certified" flag has been found in the EEPROM. The French PE3000 asks for **3 kg** because X is 3 kg; the other PE3000 asks 1 kg.
  Changing X (GUI "Cal. weight", or `set --x-digits 10000`) changes the weight the balance wants at calibration. The window is
  +-3.1 %, so calibrating the 3 kg template with 1 kg is refused; with the 1 kg template it is accepted **[hw]**.
* Nothing here makes a balance legal for trade.

## 4. DeltaDisplay (last digit blanking while the reading moves)  [rom] [emu] [hw]

The display formatter (0x5D1) blanks the last digit while bit 1 of RAM 0x8E is set and the decimal point is not on the last digit.
RAM 0x8E bit 1 is cleared by two things:

1. **Option bit (recommended):** with file byte 31 = `7F`, clearing **bit 3 of file byte 29** (F8 -> F0) disables DeltaDisplay
   without touching anything else. **Confirmed on a real PE6000: the display no longer blanks.** `pe_eeprom.py set in out --deltadisplay off`.
2. Decimal-point code 5 (file byte 20 = ...5): works too, but moves the decimal point to the last digit (5.3 g shows as 53).

A first attempt that changed file byte 21 (the threshold/stability byte) instead did not remove the blanking but made it less sensitive,
which is what the firmware numbering predicts.

## 5. Known templates (file bytes 2-3 and 20-31)

| name | 20 | 21 | 22 23 | 24 25 | 26 27 | 28 29 | 30 | 31 | X (digits) | limit (digits) |
|---|---|---|---|---|---|---|---|---|---|---|
| PE1600 | 03 | 00 | 35 00 | D0 0C | 13 8A | FF F8 | 84 | 7F | 100000 | 160090 |
| PE3000-A | 04 | 05 | 38 80 | 08 01 | 03 C9 | FF F8 | 9F | 7F | 10000 | 31009 |
| PE3000-B | 04 | 05 | A9 80 | 08 03 | 03 C9 | FF F8 | 2C | 7F | 30000 | 31009 |
| PE6000 | 04 | 2C | 71 00 | 10 02 | 07 75 | FF F8 | 06 | 7F | 20000 | 61090 |
| PE16 | 04 | 21 | E2 00 | D0 04 | 13 8A | FF F8 | BD | 7F | 40000 | 160090 |
| PE360 | 02 | 11 | 35 00 | D0 0C | 2B F4 | 53 00 | 0E | 07 | 100000 | 360090 |
| PE3600 | 03 | 05 | 35 00 | D0 0C | 2B F4 | 53 00 | 19 | 07 | 100000 | 360090 |

(byte columns are the raw file bytes in order; `pe_eeprom.py templates` prints the decoded values.)

## 6. A fresh image

`build` writes a template and either the calibration records of a donor dump or zero records (untested). Calibrate the balance afterwards;
CAL regenerates record 1. Scratch bytes 0-1 are rewritten on every standby.

## 7. Not known

* the "faster weighing-in" half of Fastmode (service bulletin ME-701763): candidates are threshold / band / filter row in file byte 21
  (see `research/RESULTS.md` for sweeps), none confirmed;
* file bytes 12-19, 28 and the exact use of the filter-row table.
