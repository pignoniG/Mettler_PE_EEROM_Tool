# Mettler PE series - MCM2801 parameter EEPROM

Reverse-engineered from the CPU firmware **ME-47455 V4.1** (National INS8050-6LPX, a mask-ROM MCS-48 part, "20-02-83")
and checked against nine EEPROM dumps (five from the author's scales, four from a 2006 forum post). The same CPU part
number is listed for the whole PE11/12/16/22/24 board family in the service manual's schematic index, and the author's
PE3000 uses it too.

Confidence tags used below:

* **[rom]** read directly from the firmware code (addresses are ROM addresses, see [docs/FIRMWARE.md](docs/FIRMWARE.md)).
* **[data]** a regularity that holds in all nine dumps.
* **[hw]** reproduced on a real balance.
* **[emu]** observed by running the firmware in the emulator in `research/`.
* **[guess]** inference; may be wrong.

## 1. The chip and the byte order

The MCM2801 is a 256-bit EAROM organised as **16 words x 16 bits = 32 bytes**, with a 4-bit address and a three-line mode
bus (CTR1-3), driven by the CPU through its data bus and port 2 bits 3-5 **[rom]**. The firmware reads *all 16 words
into RAM 0x20-0x3F* at power-on, so **byte *i* of the dump is RAM 0x20 + *i***. Dumps made with the 2801prog programmer
and the word listings published in the forum post are in this order **[data]**.

If another programmer saves each 16-bit word byte-swapped, the file reads `80 00` instead of `00 80` at bytes 2-3.
The checksums cannot reveal this (swapping the two bytes of a word leaves every block sum unchanged), so the tool decides
from that header and lets you override with `--swapped yes|no`.

## 2. Integrity checks - the rule that decides whether the balance accepts an image  [rom] [data] [hw]

At power-on the firmware runs `SUB_CA4`, which computes `0x55 + sum(N bytes)` mod 256 and requires the result to be **0**.
Equivalently **each of these three blocks must sum to 0xAB (mod 256)**:

| block | bytes | checksum byte | if it fails |
|---|---|---|---|
| calibration record 1 | 4-7 | 7 | the firmware falls back to record 2 and rewrites record 1 from it |
| calibration record 2 | 8-11 | 11 | if both records are bad: `ERROR` |
| template | 20-31 | 30 or 31 | `ERROR` |

All nine dumps satisfy all three sums, including the dump of a scale whose EEPROM could no longer be reprogrammed.

The firmware's own writer for the template (0xD00) stores `~(0x54 + sum(bytes 20..30))` in **byte 31**. In every known
PE11..PE6000 dump byte 31 is `7F` and byte 30 differs from model to model, so those dumps were made so that byte 30 absorbs
the sum. Either byte works for the firmware; `tools/pe_eeprom.py` adjusts byte 30 by default (`--adjust 31` to use the
firmware's own convention). Byte 30 is also read as data (see the table), so avoid making its low seven bits `7F`.

Bytes 0-3 and 12-19 are **not** covered by any check.

**Verified on hardware:** a French PE3000 image edited in bytes 1, 22 and 25 with byte 30 left alone sums to 0x38 and made
the balance stop with an error; the same edit with byte 30 repaired (it comes out as `9F`, byte for byte the value in the
PE3000 template) was accepted and the balance calibrated normally. `tests/` reproduces both.

## 3. Map

| bytes | RAM | content |
|---|---|---|
| 0 | 0x20 | firmware flag register. Saved with byte 1 on the standby path (`SUB_AE6`, called at 0xE99/0xED2/0xEE5) and cleared after loading. Always 00 in the dumps. **[rom]** |
| 1 | 0x21 | **scratch down-counter**, saved with byte 0. Values seen: 00, 01, D0. Not configuration, not checksummed, rewritten by the firmware (a recalibration took it from 00 to D0). Safe to ignore. **[rom][hw]** |
| 2-3 | 0x22-0x23 | `00 80` in all dumps. High nibble of byte 2 = the unit the user selected (saved by the unit-selection routine at 0xC53), index into a table at 0x367. A user setting. **[rom]** |
| 4-6 | 0x24-0x26 | **calibration record 1**: 24-bit value, least significant byte first. The live calibration factor; the CAL routine (0x905-0x9F1) rewrites only this one. **[rom][hw]** |
| 7 | 0x27 | checksum of record 1 |
| 8-10 | 0x28-0x2A | **calibration record 2**: saved/fallback copy, normally different from record 1 (it is not an exact mirror). `SUB_F03` restores record 1 from it. **[rom]** |
| 11 | 0x2B | checksum of record 2 |
| 12-19 | 0x2C-0x33 | zero in all dumps; not used by the code paths read so far |
| 20 | 0x34 | bits 0-1: threshold from ROM table {0x86,0x89,0xA3,0xC2} in the integration interrupt (0x121). bits 2-3: stability band constant {8,4,2,12} (0x17C). bits 4-5: filter row of the table at 0x396 (`SUB_3C6`); both set also changes display parameters (`SUB_B58`). **bit 6: Test (service) mode - the displayed value is doubled** **[rom][emu]**, matching the service manual ("Test mode ... double indicated value"). bit 7: calibration also overwrites bytes 22-24 with the measured value (0x93C, 0xD00), consistent with "calibration with full load" **[guess]** |
| 21 | 0x35 | bits 0-2: **resolution code** indexing an 8-entry constant table (0x4C2, 0x8B7); combined with the unit saved in byte 2 (0x52B). **Code 5 disables DeltaDisplay** (see section 4) **[rom][emu]**. The code also changes the display scaling, so do not change it on a balance whose display you want to keep |
| 22-24 | 0x36-0x38 | 24-bit constant **X**. During calibration the measured value must lie within X/32 (or X/2, see byte 27) of X, and X is multiplied into the new calibration factor (0x95C-0x9DB). What physical quantity it is is unknown **[rom]** |
| 25-27 | 0x39-0x3B | 24-bit threshold compared with the net reading (0x693). **Bit 7 of byte 27 selects the calibration window: set = X/2, clear = X/32** (0x976). The low seven bits of byte 27 are compared with 13 (0xB6A) **[rom]** |
| 28 | 0x3C | tested at 0x8D5 and 0xE78; not traced **[rom]** |
| 29 | 0x3D | `F8` in the PE11..PE6000 family; not traced |
| 30 | 0x3E | when `(byte30 & 0x7F) == 0x7F` an option byte at RAM 0xD5 is derived from byte 28 (0xE70); otherwise only the template checksum adjuster **[rom]** |
| 31 | 0x3F | template checksum byte (see section 2) |

Notes

* **There is no "certified" flag that has been found.** The service manual says Normal, Certification and Test mode differ in
  how the balance is calibrated (and Test mode doubles the display). The firmware confirms Test mode (byte 20 bit 6). What
  separates Normal from Certification in the EEPROM has not been identified; bytes 22-27 are the only candidates, and the
  two PE3000 templates differ there by +113 and +2 counts. Do not assume that editing the EEPROM can make a balance legal for trade.
* **The 1 kg / 3 kg question.** The French PE3000 template was changed to the other PE3000 template and the balance then
  calibrated with a 1 kg weight. The firmware does not contain a "weight in kg" field in bytes 22/25: both templates have
  X within 0.02 % of each other and the same X/2 window. Whether the original chip would have refused 1 kg is unknown.

## 4. DeltaDisplay (the last digit blanking while the reading moves)  [rom] [emu]

* The display formatter (0x5D1) overwrites the last digit (buffer byte RAM 0x5B) with `00` when bit 1 of RAM 0x8E is set and
  the decimal point is not on the last digit.
* Bit 1 of RAM 0x8E is maintained by `SUB_D7C` (0xD7C): set while the stability counter RAM 0x8D is below 0x40 (reading not
  settled), cleared otherwise - and **cleared unconditionally when `(RAM 0x25 & 7) == 5`**, whose low bits come from byte 21.
* Emulator, same load step, only byte 21 changed (checksum repaired): bits 0-2 = 5 -> no blanking at all; 1, 3 or 4 -> the last
  digit blanks during the transient. The French PE3000 (byte 21 = `05`) never blanks; PE16 and PE360 (`21`, `11`, code 1) and PE6000
  (`2C`, code 4) do.
* This matches the service manual: DeltaDisplay exists on PE11/PE16 and not on PE12/PE24/FE HD (those presumably carry code 5).

## 5. Known templates (bytes 2-3 and 20-31)

| name | byte 20 | 21 | 22-24 | 25-27 | 28-29 | 30 | 31 | source |
|---|---|---|---|---|---|---|---|---|
| PE1600 | 03 | 00 | 35 00 D0 | 0C 13 8A | FF F8 | 84 | 7F | own dump |
| PE3000-A | 04 | 05 | 38 80 08 | 01 03 C9 | FF F8 | 9F | 7F | own dump (scale whose EEPROM stopped accepting writes) |
| PE3000-B | 04 | 05 | A9 80 08 | 03 03 C9 | FF F8 | 2C | 7F | own dump (French-market) |
| PE6000 | 04 | 2C | 71 00 10 | 02 07 75 | FF F8 | 06 | 7F | own dump and independent forum dump agree |
| PE16 | 04 | 21 | E2 00 D0 | 04 13 8A | FF F8 | BD | 7F | forum |
| PE360 | 02 | 11 | 35 00 D0 | 0C 2B F4 | 53 00 | 0E | 07 | forum |
| PE3600 | 03 | 05 | 35 00 D0 | 0C 2B F4 | 53 00 | 19 | 07 | forum |

`pe_eeprom.py templates` prints the same data; `pe_eeprom.py build` constructs an image from one.

## 6. What a fresh image needs

`build` writes the template and either the calibration records of a donor dump or zero records (untested). The balance must be
**calibrated afterwards**: the CAL routine regenerates record 1 itself (a real calibration changed only bytes 5-6 of the
record on the author's scale). The firmware also rewrites bytes 0-1 on every standby.

## 7. Not known

* the physical meaning of X (bytes 22-24) and of the 24-bit threshold (25-27);
* what Normal vs Certification mode changes in the EEPROM;
* what Fastmode (service bulletin ME-701763, PE16: faster weighing-in, DeltaDisplay off) changes beyond DeltaDisplay.
  The DeltaDisplay half is byte 21 code 5; the "faster" half was not found in byte 20 (emulator, smooth step: bits 0-3 had no
  effect, bits 4-5 a few hundred milliseconds) - see `research/RESULTS.md`;
* the role of bytes 12-19, 28 and 29.
