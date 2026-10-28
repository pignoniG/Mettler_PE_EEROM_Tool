# Research tools

Tools used to read the format out of the firmware. They contain **no Mettler code**; they need your own dump of the CPU mask ROM,
which is not distributed (see [../docs/DUMPING_THE_CPU.md](../docs/DUMPING_THE_CPU.md)). Put it at `research/rom/ME-47455_INS8050.bin`
(git-ignored); the author's SHA-256 is in that document.

| file | |
|---|---|
| `disasm48.py` | recursive-descent MCS-48 disassembler that tracks the MB0/MB1 bank flag: `python3 disasm48.py rom/ME-47455_INS8050.bin out.asm`. About 82 % of the ROM is reached from the three vectors, with no illegal opcodes and no jumps into the middle of an instruction; the rest is data tables |
| `emu48.py` | MCS-48 emulator for this firmware: full instruction set, 256-byte RAM, MB0/MB1, the INT interrupt, an EEPROM model (the ROM's own read/write routines at 0x85D/0x83A are served from a 32-byte image), a counter-LSI model (a 12-bit count per integration cycle that you supply as a function of time), and the display read back from RAM 0xCD-0xD4 as seven segments |
| `sweep.py` | edits one template byte at a time (every single-bit flip plus 00 and FF), repairs the checksum, runs a noisy load step and compares stability time, convergence, rest flicker, blanking and display scale with the unmodified image. `python3 sweep.py 12 31 --seeds 2` (FILE byte numbers; base image is `examples/pe6000_own.bin`) |
| `hv.sh` | macOS wrapper for Millman's `hvepromcmd` (holds the serial port open so the Mega is not reset) |
| `RESULTS.md` | what the sweeps found |

## Using the emulator

```python
from emu48 import Scale
img = open('../examples/pe6000_own.bin', 'rb').read()
s = Scale('rom/ME-47455_INS8050.bin', img, count_fn=lambda cycle: 2000)   # constant counter reading
s.power_on()                   # normal power-on: standby, then the ON event -> weighing (image is in dump/file order)
print(s.display(), s.cpu.ram[0x8D])    # the display as text; RAM 0x8D = stability counter
```

Hardware that is **not** modelled: the real counter LSI protocol (only the register selection and a 12-bit count), the keyboard
beyond P1 levels, the timer interrupt, the data-interface option, EAROM timing. The counter gain in the test signal is far higher
than a real balance's, so the last digits flicker with even one count of noise; use the emulator to see *what the code does*, not
how a real balance would settle. Millisecond figures assume 2.5 us per machine cycle and one interrupt per 333 cycles; the board's
crystal is 4.915 MHz (3.05 us per cycle), so treat them as nominal and compare variants only against each other.
