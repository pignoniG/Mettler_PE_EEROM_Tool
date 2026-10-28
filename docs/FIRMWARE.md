# What is known about the ME-47455 firmware

The firmware is Mettler's property and is **not included**. This page records what the analysis found, in words and addresses
only, so that the claims in [EEPROM_MAP.md](EEPROM_MAP.md) can be checked against your own dump (see
[DUMPING_THE_CPU.md](DUMPING_THE_CPU.md); the tools in `research/` produce a listing from it).

## Identity

* Chip: National Semiconductor **INS8050-6LPX**, date code B8604 (week 4, 1986), mask-programmed by Mettler
  ("ME-47455", "(C) METTLER 1983"). An MCS-48 part: 4 KB ROM, 256 bytes RAM, 40-pin DIP. The board crystal is 4.915 MHz.
* The ROM is full: the last code byte is at 0xFF9, and the program carries its own signature text at 0xF6E -
  *"Programmer: Martin Heusser, Edit date: 20-02-83, Version: V4.1, Modify: none, uP 8050-6 : ME-47455"*.
  An 8749 (2 KB) cannot replace it.
* The service manual's schematic index lists this CPU for the whole PE11/12/16/22/24 board family; it was also fitted to the
  author's PE3000. ME-47455 replaced the earlier ME-47734 in October 1984 (service bulletin ME-701763).
* The Fastmode bulletin says only the ME-47455 can take the special PE16 bar-code table. The firmware has a path at 0x800 that
  writes 16 words (32 bytes) from a staging area at RAM 0x2C to the EEPROM; it appears to be the service-board / bar-code
  loader but has not been traced further.

## Memory use (RAM; the last rows are interpretations)

| RAM | use |
|---|---|
| 0x20-0x3F | the EEPROM image; **dump (file) byte *i* is at 0x20 + (*i* XOR 1)** because words are read low byte first; 0x20 is then used as a flag register and 0x21 as a counter |
| 0x40-0x42 | working copy of the live calibration factor |
| 0x54-0x5B | display buffer (sign/ring symbol, then seven digits) |
| 0xCD-0xD4 | display RAM scanned out by the interrupt routine (copied from 0x54-0x5B by `SUB_B3B`) |
| 0x8D | stability counter (0x7F = settled; falls toward 0 while the reading moves) |
| 0x8E | state flags: bit 0 "new reading", bit 1 DeltaDisplay, bit 4 set every processing pass (cleared and waited on by `SUB_665`), bit 7 set/cleared from a carry at 0x45D |
| 0x6F, 0x51, 0x29-0x2B | probably the zero reference, a ROM constant (0x7FFFFF) and the reading being processed |

All arithmetic is on **24-bit values, least significant byte first** (add, subtract, shift, a 24x24 multiply and a restoring
divide at 0x200-0x2C8 and 0xA00-0xA9F), with constants fetched from a ROM table on page 3.

## Interrupt routine (0x003)

Entered at each integration cycle of the counter LSI. It reads the LSI three times (port 1 bits 4-5 select the register: a dummy
read, the low byte, then the high nibble with status), accumulates the counts in RAM 0xC1/0xC2, scans one display digit out
(segments latched by P2.1, digit select by P2.0 from the table at 0x300), and every eight cycles calls the processing at 0x100.
The processing reads firmware template byte 20 (file byte 21) for its thresholds and band constants and, every 30 passes, sets the "new reading" flag
that the main loop at 0x400 waits for.

## EEPROM driver

* `SUB_884` sends the 4-bit word address, `SUB_83A` writes R2 words from RAM at R0 to address R1, `SUB_85D` reads. The data
  travels over the bus; the mode is set on P2.3-P2.5 (address 001, data 101, erase/write pulses 100 and 010 with long delays,
  read 011 then 110 - the last grouping is inferred); `SUB_B53` is the strobe.
* The only read is at power-on (0xE1F, all 16 words). Writes: whole-template (0xD00), calibration record 1 (0x9F1), the
  record restore (`SUB_F03`), the unit setting (0xC5B) and the scratch word (`SUB_AE6`).
* Validation (0xE31-0xE4D): see [EEPROM_MAP.md](EEPROM_MAP.md) section 2.

## Calibration routine (0x905-0x9F1)

Waits for a stable reading, subtracts template constant X (firmware bytes 22-24 = file bytes 23, 22, 25) from it and requires the difference to be smaller than
X/32 or X/2 (firmware byte 27 bit 7 = file byte 26 bit 7); after enough consecutive good passes it multiplies X into the previous factor, divides by the
measured value and the zero reference, and stores the result as record 1 (24 bits + checksum, written to EEPROM words 2-3).
If firmware template byte 20 bit 7 (file byte 21) is set the measured value is written back into X instead (0xD00).

## Display

`0x575-0x5F7` formats the weight into the display buffer using the seven-segment table at 0x333 and the unit/decimal-point
constants selected by the unit nibble and the code in file byte 20. Message strings (CAL, no, Unit, OFF, Error, ----) are seven-segment byte strings in the ROM at
0xAF5-0xB2F and 0x35E-0x366. The DeltaDisplay blanking is at 0x5D1 (see EEPROM_MAP.md section 4).

## Inputs seen by the code (from the schematic and the code)

P1.0 and P1.2 are read at power-on (0xE87): in the emulator, holding P1.0 low (the key line on the schematic) at power-on enters the
unit-selection state (which rewrites the saved unit, so use `Scale.power_on()` for tests), and releasing it continues to weighing; with P1.0 high the firmware goes to standby (display `OFF`). The
interrupt routine also samples P1 bits 2-3 (0x1D2-0x1F3), and the data-interface option is polled with MOVX at 0x3F.
