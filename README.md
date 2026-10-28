# Mettler PE parameter EEPROM tool

Decode, verify, edit and rebuild the parameter EEPROM (an **MCM2801 EAROM**, 32 bytes) of Mettler **PE series** precision
balances - PE11/12/16/22/24, PE360/3600, PE1600/PE3000/PE6000 and relatives, the electromagnetic-force-compensation
balances of the 1980s with a National INS8050 / ME-47455 processor.

The chip holds the balance's calibration factors and a small "model + mode" template that the firmware reads at power-on.
If it is blank, damaged or has lost its data - a known failure of these old EAROMs - the balance shows `ERROR`. The
numbers were normally written with a Mettler bar-code reader and a printed code table that is hard to find today. This
repository documents the format and provides a tool that rebuilds a valid image from nothing but a programmer.

Everything here was read out of the CPU firmware (dumped from a real board, see [docs/DUMPING_THE_CPU.md](docs/DUMPING_THE_CPU.md))
and checked against nine EEPROM dumps. **The tool only touches the EEPROM image; it does not modify firmware.** The
firmware itself is Mettler's and is **not** in this repository. A sister project covers the later AM/PM balances:
[Mettler_PM_UnofficialServiceTool](https://github.com/pignoniG/Mettler_PM_UnofficialServiceTool).

**[EEPROM_MAP.md](EEPROM_MAP.md) documents the format** - the integrity rules, what each byte does, the known model
templates and what is still unknown. Read that if you want to understand a dump rather than just repair it.

> **Working on a balance is your responsibility.** These are measuring instruments. Save your original dump before
> writing anything and keep it. If your instrument is legal-for-trade or otherwise verified, changing calibration data
> invalidates that - and nothing here can make an instrument certified: no certification flag has been identified.

## What it can do

- **Decode a dump**: the three checksum blocks, both calibration records, every template field it understands (Test mode,
  DeltaDisplay, resolution code, the calibration window) and the closest known model template.
- **Repair the checksums** after any edit, byte-exact the way the balance checks them. This is the thing that makes a hand-edited
  image acceptable: a template changed without fixing the sum is rejected with `ERROR` (reproduced on a real PE3000).
- **Edit** a raw byte or a named field: Test mode on/off, DeltaDisplay on/off, the two 24-bit calibration records.
- **Rebuild an image** from a known model template plus either the calibration records of a donor dump or zero records.
- **Convert** between a binary dump and the 16-word hex listing used in forum posts; **diff** two dumps.
- Works on dumps whose 16-bit words were saved byte-swapped by the programmer (detected from the `00 80` header).

## Quick start

```bash
python3 tools/pe_eeprom.py info examples/pe3000_B_french_original.bin     # decode + checksum state + closest template
python3 tools/pe_eeprom.py verify mydump.bin                              # exit status 0 only if the balance would accept it

# edit, then repair - one step; nothing is written without an output file name
python3 tools/pe_eeprom.py set mydump.bin edited.bin --deltadisplay off --dry-run
python3 tools/pe_eeprom.py set mydump.bin edited.bin --test-mode on
python3 tools/pe_eeprom.py set mydump.bin edited.bin --byte 22=0x38 --byte 25=0x01     # raw bytes, sums repaired

# rebuild a lost EEPROM from a template (best: copy the calibration records from a dump of the same scale)
python3 tools/pe_eeprom.py templates
python3 tools/pe_eeprom.py build --template PE6000 --out new.bin --donor examples/pe6000_own.bin
```

After programming any modified or rebuilt image, **calibrate the balance** with its calibration weight; the calibration routine
regenerates the live calibration record itself.

## What has and has not been verified

| | status |
|---|---|
| the three-sum integrity rule | read from the firmware; holds in all 9 dumps; **a real PE3000 rejected an image that broke it and accepted the repaired one** |
| Test mode = byte 20 bit 6 | read from the firmware, observed in the emulator, matches the service manual |
| DeltaDisplay off = byte 21 bits 0-2 equal to 5 | read from the firmware and observed in the emulator; **not yet tried on a real balance** |
| rebuilding from a template | reproduces all seven known templates with their own records (unit tests); **no balance has been brought up from a rebuilt image yet**; zero calibration records are untested |
| meaning of bytes 22-27, Normal vs Certification, Fastmode speed | unknown, see [EEPROM_MAP.md](EEPROM_MAP.md) section 7 |

## Reading and writing the chip

The MCM2801 (a 16 x 16-bit serial EAROM) needs a programmer that knows it; the author used the 2801prog from
Dasaro Designs. Read the chip **twice** and compare before you change anything. A chip that has lost its data can also fail to
accept a new calibration - one of the author's chips still reads fine but cannot be rewritten, while the scale keeps working
from its existing contents.

A dump is exactly 32 bytes. Programmers differ in the byte order of 16-bit words; the tool detects the common swap and writes
the file back in the order it read it. Override with `--swapped yes|no` if a file is misjudged.

## Repository layout

| path | |
|---|---|
| [`tools/pe_eeprom.py`](tools/pe_eeprom.py) | the tool (Python 3.8+, standard library only); `templates.json` is its template library |
| [`EEPROM_MAP.md`](EEPROM_MAP.md) | the format, byte by byte, with evidence tags |
| [`docs/FIRMWARE.md`](docs/FIRMWARE.md) | what is known about the ME-47455 firmware (no code is reproduced) |
| [`docs/DUMPING_THE_CPU.md`](docs/DUMPING_THE_CPU.md) | how the CPU mask ROM was read with an MCS-48 programmer |
| [`examples/`](examples/) | the nine example EEPROM dumps and where they came from |
| [`tests/`](tests/) | unit tests (`python3 -m unittest discover -s tests`) |
| [`research/`](research/) | an MCS-48 disassembler, an emulator that runs the firmware, and the parameter sweep; **needs your own dump of the CPU ROM, which is not included** |

## Credits

The four forum dumps (PE360, PE3600, PE6000, PE16) were posted in 2006 by David Smith. The MCS-48 reader used to dump the
CPU is Matt Millman's open design (`mattmillman.com`, github `inaxeon/eightoduino`). The 2801prog programmer is by Dasaro Designs.

## License

MIT - see [LICENSE](LICENSE).
