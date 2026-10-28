# Model families, boards and hardware switches

Collected from the user manuals, the service manual and the IES service handbook (`HB CALIBRAZIONE BILANCE.doc`). It explains which behaviours
live in the EEPROM and which in hardware; see [EEPROM_MAP.md](../EEPROM_MAP.md) for the byte format.

## Calibration weights (IES handbook) vs the weight stored in the EEPROM

| model | handbook calibration weight | X in the dumps (file bytes 23, 22, 25) |
|---|---|---|
| PE160, PE300 | 100 g | (no dump) |
| PE360 | 100 g | 100 g (100000 digits at 0.001 g) |
| PE600 | 500 g | (no dump) |
| PE1600, PE3000, PE3600 | 1000 g | 1 kg for the PE1600, PE3600 and one PE3000; **3 kg for the French-market PE3000** |
| PE6000, PE6 | 2000 g | 2 kg (PE6000) |
| PE11, PE12, PE16, PE24 | 4000 g | 4 kg (PE16) |

So X really is the calibration weight; the handbook's weights agree with every decoded dump except the French PE3000, which was configured for 3 kg.
User calibration: tare, press and hold TARE until the horizontal bars appear, release; CAL shows, then put the weight on the pan. Units: hold TARE while powering on
and release when the unit you want appears (this saves the unit in file byte 3, high nibble).

## Board families (IES handbook "PE - Pots & Boards")

The handbook lists the main-board numbers on the yellow tag under the board. The table in the document is laid out in columns that did not survive conversion, so treat the
grouping below as approximate:

* **PE160, 360, 600, 1600, 3600, 6000**: boards 47050, 48334, 47484 (and 47823); linearity pot R60, temperature-compensation pots R59 / R64, **software calibration**.
* **PE200, 400, 2000, 4000**: boards 47507, 47662; **calibration by pot R32, no EEPROM calibration**, linearity R34, TC R33. A different design, see below.
* **PE11, 12, 16, 22, 24**: boards 48391 / 48979; linearity R57, TC R59 / R58, software calibration.
* **PE160A, PE1600A**: board 47818; **FE HD, FE HD2**: board 45755 (and 48391).

Do not swap boards between models unless the part numbers match: the handbook says the balance then drifts and cannot be compensated, because the board is matched to the cell.

## Features that are hardware on some models

* **PE200 / 400 / 2000 / 4000 (user manual `pe200.pdf`)**: two slide switches directly behind the display. Switch (20) switches **DeltaDisplay and the stability detector** on/off; switch (21)
  **doubles the integration time** (1.25 s -> 2.5 s). The specification gives the display sequence as 0.15 s with DeltaDisplay on and 0.6 s with it off (doubled with the long integration time).
  These two features are therefore hardware switches on this family, **not** EEPROM bits. The PE3000/PE6000-type boards do not have the switches; on them the firmware reads DeltaDisplay
  from the EEPROM option bit (EEPROM_MAP.md section 4).
  * The emulator does **not** show a speed difference for DeltaDisplay on/off on the PE6000 firmware: the update interval is the same about 0.2 s (nominal) either way. The 0.15 s / 0.6 s figures
    of the PE200 may come from its different board and ROM, or from the stability detector and integration time, which the emulator does not model.
* **PE360 DeltaRange / PE3600 DeltaRange (`pe360_deltarange.pdf`)**: a fine range 60 g / 600 g with ten times the readability inside the coarse range, selected in the EEPROM by the
  fine-range limit in file bytes 29, 28 and 31 (EEPROM_MAP.md section 2). Beyond the limit the last decimal place is blanked.
* **Certified balances**: calibration and unit selection are blocked by a short-circuit plug (ST4 in the manual, ST2 on the schematics we have), not by the EEPROM.
