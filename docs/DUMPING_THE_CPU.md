# Dumping the CPU mask ROM

You only need this if you want to run the research tools or check the claims in [EEPROM_MAP.md](EEPROM_MAP.md) against the
firmware yourself. The EEPROM tool does not need it.

The balance CPU (INS8050-6LPX, Mettler code ME-47455) is an MCS-48 part with a 4 KB mask ROM. MCS-48 chips largely predate
read protection, and this one reads out. A mask-ROM part can be read with an MCS-48 programmer that applies +12 V to the EA pin;
a universal programmer such as the XGecu T48 / minipro **cannot** (it has no MCS-48 algorithms, and the T48 firmware algorithms are
closed bitstreams). The dump was made with Matt Millman's open design:

* MCS-48 shield on an Arduino Mega 2560 (`mattmillman.com/projects/hveprom-project`, github `inaxeon/eightoduino`,
  `inaxeon/hvepromcmd`). Reading 8048/8049/8050 mask ROMs needs only +5 V and the +12 V EA drive.
* Not every mask-ROM MCS-48 can be read: customers could order read-out disabled. A protected part returns noise, so read twice
  and compare.

## What was done (macOS, Mega 2560 clone with a CH340 USB-serial chip)

1. **Remove the CPU from the board** (desolder or socket); the programmer powers it itself. Handle it as the only copy of the firmware.
2. **Flash the programmer firmware** (the precompiled `hveprom.hex` from the repository, the USB build). The usual `-c arduino` and
   `-c wiring` options timed out on this clone; the Mega's bootloader answered on `-c stk500v2`:
   `avrdude -c stk500v2 -P /dev/cu.usbserial-XXXX -b 115200 -D -p atmega2560 -U flash:w:hveprom.hex:i`
   (signature 1E 98 01 = ATmega2560; Millman's page lists the same three protocol variants).
3. **Build the host tool** `hvepromcmd` (`make`; it compiled on macOS with only warnings).
4. **macOS quirk:** opening the serial port pulses DTR and resets the Mega into its bootloader for a few seconds, so the first command is
   lost and the tool reports "Timed out attempting to communicate with the target". `research/hv.sh` holds the port open while
   `hvepromcmd` runs; put the built `hvepromcmd` next to it and edit the port name in the script.
5. **Power:** the shield needs a regulated ~12 V supply on the Mega's barrel jack (the host tool accepts 10-14 V; an unplugged shield or
   USB-only power reads about 4.5 V and fails with "must be connected to a 12V supply").
6. **Run the hardware self-test with the CPU socket empty** and check each of the ten steps with a multimeter (black probe on pin 20, within 5 %):
   `./hv.sh -o test -s MCS48`. On the author's build every step passed except EA at 12 V, which read 12.83 V (about 7 % high). Intel's datasheet
   names 12 V for ROM verification on the 8048/8049/8050 and 17.5-18.5 V for the EPROM versions' EA pin, and the read worked.
7. **Read twice and compare:**
   `./hv.sh -o read -d 8050 -f run1.bin` and again to `run2.bin`; `shasum -a 256 run*.bin` must match, and the file must be exactly 4096 bytes.

## What the result looked like

Two identical 4096-byte reads, 245 distinct byte values, code starting `F5 C4 00` (select memory bank 1, jump to 0x600), interrupt vector 3
starting with `D5` (select register bank 1), last code byte at 0xFF9 and a readable signature string at 0xF6E. A protected part would
have returned different data on each read.

The author's dump has SHA-256 `35cf70ead68ea795c3bef719d00d1841f4d4a20a7a033c8e02a489db3a0002fc`. Put yours in
`research/rom/ME-47455_INS8050.bin` (that directory is ignored by git) and compare.
