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
templates and what is still unknown. Byte numbers everywhere are **file (dump) byte numbers**; the firmware sees each 16-bit word
swapped (file byte *i* = firmware byte *i XOR 1*), explained in section 0 of that document.

> **Working on a balance is your responsibility.** These are measuring instruments. Save your original dump before
> writing anything and keep it. If your instrument is legal-for-trade or otherwise verified, changing calibration data
> invalidates that - and nothing here can make an instrument certified. Certified balances block user calibration with a hardware short-circuit plug (ST4), not an EEPROM bit.

## What it can do

- **Decode a dump**: the three checksum blocks, both calibration records, every template field it understands (Test mode,
  DeltaDisplay, decimal-point code, calibration weight, overload limit, calibration window) and the closest known model template.
- **Repair the checksums** after any edit, byte-exact the way the balance checks them. This is the thing that makes a hand-edited
  image acceptable: a template changed without fixing the sum is rejected with `ERROR` (reproduced on a real PE3000).
- **Edit** a raw byte or a named field: Test mode on/off, DeltaDisplay on/off, the calibration weight and overload limit, the two 24-bit calibration records.
- **Rebuild an image** from a known model template plus either the calibration records of a donor dump or zero records.
- **Convert** between a binary dump and the 16-word hex listing used in forum posts; **diff** two dumps.
- Works on dumps whose 16-bit words were saved byte-swapped by the programmer (detected from the `00 80` header).
- **A GUI** (`tools/pe_eeprom_gui.py`) with a colour-coded byte grid, live checksum status, the decoded fields as controls, undo,
  a change log and a compare mode - see below.

## Quick start

```bash
python3 tools/pe_eeprom.py info examples/pe3000_B_french_original.bin     # decode + checksum state + closest template
python3 tools/pe_eeprom.py verify mydump.bin                              # exit status 0 only if the balance would accept it

# edit, then repair - one step; nothing is written without an output file name
python3 tools/pe_eeprom.py set mydump.bin edited.bin --deltadisplay off --dry-run
python3 tools/pe_eeprom.py set mydump.bin edited.bin --test-mode on
python3 tools/pe_eeprom.py set mydump.bin edited.bin --x-digits 10000                 # ask for a 1 kg calibration weight (at 0.1 g)
python3 tools/pe_eeprom.py set mydump.bin edited.bin --byte 29=0xF0                    # raw FILE byte, sums repaired

# rebuild a lost EEPROM from a template (best: copy the calibration records from a dump of the same scale)
python3 tools/pe_eeprom.py templates
python3 tools/pe_eeprom.py build --template PE6000 --out new.bin --donor examples/pe6000_own.bin
```

## The GUI

```bash
python3 tools/pe_eeprom_gui.py                 # or give it a dump:  python3 tools/pe_eeprom_gui.py mydump.bin
```

* **Byte grid**: click a byte and type two hex digits. Colours mark the scratch bytes, the header, the two calibration records, the unused bytes,
  the template and the checksum bytes; the line under the grid explains the selected byte. Bytes that differ from the file as opened are red.
* **Integrity panel**: the three block sums and OK/BAD. With *auto-repair* on (the default) an edit fixes only the checksum of the block it touched -
  a record edit fixes byte 6 or 10, a template edit fixes byte 30 - while editing a checksum byte yourself is left alone, so you can still
  make an invalid image on purpose. The header badge says whether the balance would accept the image.
* **Fields**: the two calibration records, Test mode, grouped in three tabs (Display, Calibration, Response), each control with a plain-language explanation: DeltaDisplay on/off, decimal-point code,
  Test mode, calibration weight, overload limit, DeltaRange limit, calibration window, threshold / stability band / filter row. *Closest known templates* ranks the library against the open image and can apply one (the scale's own calibration
  records are kept).
* **Undo** goes back through every edit; *Revert* returns to the file as opened; *Save as* writes in the byte order the file came in. The **change log**
  lists every edit with before and after values. *Copy as words* / *Paste words...* use the 16-word listing of forum posts. *File > New image from template*
  rebuilds an image from a template.

Nothing is written until you choose *Save as*, and the editor warns before saving an image whose checksums are bad.
It needs `tkinter` (part of the standard Python installers; on some Linux systems `apt install python3-tk`).

After programming any modified or rebuilt image, **calibrate the balance** with its calibration weight; the calibration routine
regenerates the live calibration record itself.

## What has and has not been verified

| | status |
|---|---|
| the three-sum integrity rule | read from the firmware; holds in all 9 dumps; **a real PE3000 rejected an image that broke it and accepted the repaired one** |
| Test mode = file byte 21 bit 6 | read from the firmware, observed in the emulator, matches the service manual |
| DeltaDisplay off = file byte 29 bit 3 cleared (byte 31 = 7F) | **confirmed on a real PE6000: no more last-digit blanking** |
| rebuilding from a template | reproduces all seven known templates with their own records (unit tests); **no balance has been brought up from a rebuilt image yet**; zero calibration records are untested |
| the GUI | 25 widget-level checks (typing into cells, toggles, Set buttons, templates, undo, save/reopen, compare); only used on dump files |
| calibration weight (X) and limit | read from the firmware; X matches the 1 kg / 3 kg behaviour of two real PE3000 |
| Normal vs Certification, Fastmode speed | unknown, see [EEPROM_MAP.md](EEPROM_MAP.md) section 7 |

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
| [`tools/pe_eeprom.py`](tools/pe_eeprom.py) | the command-line tool (Python 3.8+, standard library only); `templates.json` is its template library |
| [`tools/pe_eeprom_gui.py`](tools/pe_eeprom_gui.py), [`tools/pe_editor.py`](tools/pe_editor.py) | the GUI and the editing model behind it (the model has no GUI code and is unit-tested) |
| [`EEPROM_MAP.md`](EEPROM_MAP.md) | the format, byte by byte, with evidence tags |
| [`docs/FIRMWARE.md`](docs/FIRMWARE.md) | what is known about the ME-47455 firmware (no code is reproduced) |
| [`docs/MODELS.md`](docs/MODELS.md) | model families, board numbers, calibration weights, which features are hardware switches (PE200) or EEPROM fields (DeltaRange) |
| [`docs/CPU_PINS.md`](docs/CPU_PINS.md) | what the firmware drives and reads on each CPU pin (for anyone replacing a dead CPU; inferred from the code, not scoped) |
| [`docs/DUMPING_THE_CPU.md`](docs/DUMPING_THE_CPU.md) | how the CPU mask ROM was read with an MCS-48 programmer |
| [`examples/`](examples/) | the nine example EEPROM dumps and where they came from |
| [`tests/`](tests/) | 28 unit tests (`python3 -m unittest discover -s tests`) and `gui_smoke.py`, which drives the real widgets (needs a display; run by hand) |
| [`research/`](research/) | an MCS-48 disassembler, an emulator that runs the firmware, and the parameter sweep; **needs your own dump of the CPU ROM, which is not included** |

## Credits

The four forum dumps (PE360, PE3600, PE6000, PE16) were posted in 2006 by David Smith. The MCS-48 reader used to dump the
CPU is Matt Millman's open design (`mattmillman.com`, github `inaxeon/eightoduino`). The 2801prog programmer is by Dasaro Designs.

## License

MIT - see [LICENSE](LICENSE).
