# Example EEPROM dumps

Nine 32-byte MCM2801 dumps, all of which satisfy the integrity rule in [EEPROM_MAP.md](../EEPROM_MAP.md) section 2
(`python3 tools/pe_eeprom.py verify examples/<file>`). Use them as reference data or as the donor of calibration records
when rebuilding an image for the same scale. **Calibration records are per scale**: do not copy them between different units.

| file | scale | source | notes |
|---|---|---|---|
| `pe1600_own.bin` | file named "pe1600" (PE1600 family) | author | identity not independently confirmed |
| `pe3000_A_faulty-chip.bin` | PE3000 | author | EEPROM that no longer accepts writes; the contents are valid and the scale worked. File byte 0 reads 00 (scratch byte) |
| `pe3000_B_french_original.bin` | PE3000, French market | author | original contents of the chip that was later edited |
| `pe3000_B_french_after_edit_and_calibration.bin` | same scale | author | read back after the template was changed to the PE3000-A values (file bytes 1, 22, 25, 30) and the scale was calibrated with a 1 kg weight: only the calibration record (file bytes 4-5) and scratch byte 0 differ from the written image |
| `pe6000_own.bin` | PE6000 | author | |
| `pe360_forum.bin`, `pe3600_forum.bin`, `pe6000_forum.bin`, `pe16_forum.bin` | PE360, PE3600, PE6000, PE16 | forum post by David Smith, 2006 ("values found in my Mettler EEPROMs") | transcribed from the post's 16-word listings; the PE6000 agrees with the author's own PE6000 in every template byte |

The forum listings are 16 hex words per scale, top to bottom in address order; `pe_eeprom.py from-words` converts such a listing to a binary
file and `to-words` does the reverse.
