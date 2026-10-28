#!/bin/bash
# Wrapper for hvepromcmd on macOS.
# Opening the Mega's serial port pulses DTR and resets the board into its bootloader for a few seconds,
# so the first command is lost and hvepromcmd reports "Timed out". Holding the port open while
# hvepromcmd runs keeps the Mega out of the bootloader.
#
# Usage:  ./hv.sh -o test -s MCS48
#         ./hv.sh -o read -d 8050 -f ME-47455.bin
# (-p PORT is added automatically; override the port with PORT=/dev/cu.xxx ./hv.sh ...)

PORT="${PORT:-/dev/cu.usbserial-3120}"
cd "$(dirname "$0")" || exit 1

exec 3<"$PORT" || { echo "Cannot open $PORT"; exit 1; }
echo "Waiting 5s for the Mega to finish resetting..."
sleep 5
./hvepromcmd "$@" -p "$PORT"
rc=$?
exec 3<&-
exit $rc
