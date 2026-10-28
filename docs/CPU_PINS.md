# What the ME-47455 firmware drives and reads (pin-level interface)

Written for anyone who has to replace a dead INS8050 (MCS-48 family, 40-pin DIP, 4 KB mask ROM, 256 B RAM). It is derived **only from the firmware
code** (opcode-level, from a dump of the ROM) and has not been checked against a real board with a scope. Names of what is on the other end of each pin are
**inferences**; check them against the schematics ES-45785 / ES-47452 in the service manual before building anything. Addresses are ROM addresses, see
[FIRMWARE.md](FIRMWARE.md).

Tags: **[code]** read directly from the instructions; **[infer]** interpretation of what the pin is connected to.

## What the replacement must do besides running the code

* Execute the MCS-48 instruction set with the original **cycle timing**: the crystal is 4.915 MHz, so one machine cycle (15 clocks) is about 3.05 us. The counter
  interrupt, the display multiplex and the EAROM waits all count machine cycles.
* **256 bytes of internal RAM** (the firmware uses addresses up to 0xFF, including both register banks and the stack), 4 KB of program space with the MB0/MB1 bank
  switching (`SEL MB0/MB1`), and the page-3 `MOVP3` table reads.
* **Reset** vector 0x000, **external-interrupt** vector 0x003 (this is the integration-cycle interrupt, see below). The **timer/counter is never started** (no `STRT T`,
  `STRT CNT` or `EN TCNTI` in the code); `MOV T,A` and `MOV A,T` are only used as a spare register. No `T0` clock output.
* The bus (`BUS`, port 0) is used in **both directions** with `OUTL BUS,A`, `INS A,BUS` and `MOVX`, so the replacement needs a proper bidirectional 8-bit bus with
  the `RD`/`WR` strobes (pins 8 and 10) for the `MOVX` accesses, and quasi-bidirectional ports 1 and 2.

## Port 1 (quasi-bidirectional, 8 bits)

| pin | direction | what the firmware does | meaning **[infer]** |
|---|---|---|---|
| P1.0 | in | read at reset (0xE87) to choose between the unit-selection state and standby; sampled every interrupt pass for press/release (0x1D4-0x1EA); a press held for about 20 passes (RAM 0x83 = 0x14) enters calibration | the front **key** (CAL/tare) line, active low |
| P1.1 | out | pulsed high then low (`ORL P1,#02`, `ANL P1,#FD`) after each `OUTL BUS,A` at 0x7C5, 0x7CD, 0x7DC, 0x8C8 | a **strobe/clock** for an auxiliary output, probably the data interface (the bytes written come from RAM 0xC3/0xC4 and are rotated bit by bit) |
| P1.2 | in | read at reset (0xE87), at the start of **calibration (0x905)** and of unit selection, and in the calibration-weight/constant selection (0x6C2, 0xF5D); sampled each interrupt pass | **calibration lock**: the service manual's short-circuit plug **ST4** on certified balances. Low = calibration and unit selection are refused. It also selects between two constants (RAM 0x40 or 0x43) in the weight comparison, so it changes more than the lock |
| P1.3 | in | debounced into bit 0 of RAM 0x20 (0x502); a second input | a second **key/switch** line (not identified) |
| P1.4, P1.5 | out | `ANL P1,#CF` then `ORL P1,#20` then `ORL P1,#10` around the three `MOVX` reads in the interrupt routine (0x008-0x018) | **register select** of the counter LSI (00 for the first two reads - a dummy read and the low byte - then 10 for the high nibble and status; the pins are left at 11 afterwards) |
| P1.6 | out | pulsed low then high (`ANL P1,#BF`, `ORL P1,#40`) together with `OUTL BUS` at 0x0E4 | strobe for the data-interface output byte (with P2.6) |
| P1.7 | out | pulled low around the `MOVX A,@R0` reads at 0x04F-0x052 and 0x08F-0x094, then high | **chip select** for a read of the data-interface input latch |

## Port 2 (quasi-bidirectional, 8 bits)

| pin | what the firmware does | meaning **[infer]** |
|---|---|---|
| P2.0 | pulsed high/low (`ORL P2,#01`, `ANL P2,#FE`) after `OUTL BUS` at 0x033 | latches the **digit select** pattern (from the ROM table at 0x300, indexed by the digit counter R6) for the display multiplex |
| P2.1 | pulsed after `OUTL BUS` at 0x02B-0x02E with the segment byte from RAM 0xCD-0xD4 | latches the **segment data** for the current digit (the first `OUTL BUS,0` + P2.0/P2.1 pulse at 0x021-0x024 blanks the display before the next digit) |
| P2.2 | pulsed by `SUB_B53` (0xB53: `ORL P2,#04`, `ANL P2,#FB`) after every EAROM bit and at reset (0xE03) | the **EAROM clock/strobe** |
| P2.3, P2.4, P2.5 | set to 111 (`ORL P2,#38`) then cleared bit by bit (`ANL P2,#EF/E7/D7/DF/F7/CF`) | the **EAROM mode lines** CTR1-3 of the MCM2801: the driver uses address = 001, data write = 101, erase = 100, write = 010, read = 011 then 110 (CTR3..CTR1 reading P2.5, P2.4, P2.3) |
| P2.6 | pulsed (`ORL P2,#40`, `ANL P2,#BF`) at 0x0E9 and 0x0F5 and tested with `T1` | **data-interface handshake output** (with P1.6) |
| P2.7 | pulled low after the data-interface input reads (0x056, 0x092, 0x09E, 0x0B7); set at 0x06F | **data-interface handshake / acknowledge** line |

## Bus (port 0)

* **Output** (`OUTL BUS,A`): display segment and digit data (0x021-0x032), the EAROM address and data bits one bit at a time (SUB_879/SUB_884, 8 bits per byte, least significant
  bit first, with a P2.2 strobe per bit), the data-interface output byte (0x0E4, 0x7C5...), and a zero at reset (0xE00).
* **Input** (`INS A,BUS` at 0x899): the EAROM data, one bit per strobe, 8 bits per byte.
* **`MOVX A,@R0`** reads (RD strobe): the **counter LSI** (three reads per interrupt, selected by P1.4/P1.5, 0x007-0x017) and the data-interface input latch (selected by P1.7).
  The address in R0 is never decoded by anything on the bus (the high address byte is not driven in 8-bit `MOVX` mode), so the select lines above are what matters.
* No `MOVX @R0,A` writes are executed anywhere in the ROM.

## Test inputs and interrupt

| pin | direction | firmware use |
|---|---|---|
| **INT** (pin 6) | in | the **integration-cycle interrupt**: a pulse from the counter LSI at the end of each A/D integration cycle (the interrupt routine at 0x003 reads the counter and scans one display digit every cycle). Also polled with `JNI` while waiting for the EAROM write cycle (SUB_8A7 loops until the pin is high after each program pulse; the interrupt is disabled with `DIS I` during EAROM access and re-enabled with `EN I`) |
| **T0** (pin 1) | in | tested with `JT0`/`JNT0` at 0x04B and 0x06D in the data-interface handling |
| **T1** (pin 39) | in | tested with `JNT1`/`JT1` at 0x0D8 and 0x0F1 in the data-interface handling |
| RESET | in | the firmware starts at 0x000, selects MB1 and jumps to 0xE00 |
| XTAL1/XTAL2 | | 4.915 MHz crystal |
| EA | in | must be low so that the internal ROM is used (the Millman reader raised EA to 12 V only to read the ROM) |
| PSEN, ALE, PROG | | not used by the code (no external program memory, no `MOVD`/`ANLD`/`ORLD`) |

## Sequences a replacement has to reproduce exactly

1. **Counter read** (every interrupt): `ANL P1,#CF` (P1.4/5 = 00); `MOVX A,@R0` twice (dummy, then the low byte); add with carry; `ORL P1,#20` (10); `MOVX A,@R0` (high nibble and status); `ORL P1,#10` (11). Without the right select pattern on P1.4/P1.5 the
   weighing value is garbage.
2. **Display scan** (every interrupt): `OUTL BUS,0` + pulse P2.0|P2.1; `OUTL BUS,segment` + pulse P2.1; `OUTL BUS,digit` + pulse P2.0. One digit per interrupt; the multiplex rate is the
   integration-cycle rate.
3. **EAROM access**: each read or write is a sequence of mode changes on P2.3-P2.5 with a P2.2 pulse per bit and long waits on `JNI`; see FIRMWARE.md. The cell stores 16 words of 16 bits; the CPU
   reads and writes the low byte of each word first.
4. **Power-on**: `OUTL BUS,0`; `ANL P2,#F8` (P2.0-2 low); a P2.2 pulse; then the 16-word EAROM read (0xE1F) and the integrity check (0xCA4).

## What is not known

* The exact connection of P1.1, P1.6, P1.7, P2.6, P2.7, T0 and T1 (the optional data interface is the best guess; check the schematic).
* P1.3's role.
* Whether the RD strobe or the `MOVX` address matters to the LSI or the data interface (the address in R0 is 0xC1, 0xC2, 0x7E, 0x7F, etc.; a replacement that does not drive an address bus is
  as good as the original only if the board does not decode it).
