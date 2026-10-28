# Emulator results

All runs: the French PE3000 EEPROM image, checksum repaired after every edit, power-on with the key line held then released, a
steady count, then a load step. Time figures are nominal (see [README.md](README.md)); only the comparisons between variants mean anything.

## DeltaDisplay - solved

Only byte 21 changed (same noisy load step):

| byte 21 | bits 0-2 | frames with the last digit blank | RAM 0x8E bit 1 |
|---|---|---|---|
| 0x05 (as shipped) | 5 | 0 | never set |
| 0x01 / 0x21 | 1 | 7 | set during the transient |
| 0x03 | 3 | 7 | set during the transient |
| 0x04 | 4 | 7 | set during the transient |

Code 5 disables DeltaDisplay. Byte 21 bits 0-2 also select the base resolution constant, so the display scaling can change with them.

## Test mode - confirmed

Byte 20 bit 6 set doubles the displayed value for the same input (27877 -> 55755), matching the service manual's service mode.

## Byte 20 and settling speed - no Fastmode switch found

Smooth exponential load step, no noise (stability = the stability counter RAM 0x8D falls below 0x20 and returns to 0x7F):

| byte 20 | time to stable | displayed value within 1000 digits | within 1 digit |
|---|---|---|---|
| 0x04 (as shipped), 0x00, 0x01, 0x02, 0x08, 0x0C, 0x20, 0x40, 0x80 | 1965 ms (same for all) | 1099 ms | about 9.3 s |
| 0x10 | same | 1099 ms | about 9.1 s |
| 0x30 | 2338 ms | 1299 ms | about 9.9 s |
| 0x03 | display becomes unreadable | | |

So bits 0-3 do not change how fast the reading is declared stable in this test, and bits 4-5 change convergence only slightly.
An early result suggesting 0x08/0x10 were nine times faster was an artifact of the stability counter already decaying when the step began.

## Template bytes 23-29, one at a time, with noise - in progress

`python3 sweep.py 23 29 --seeds 3` (every single-bit flip plus 00 and FF of each byte; metrics: displayed value for the same load,
time to unstable and stable, time to settle within 100 digits, rest flicker, blanking). The table will be added here when the run finishes.
