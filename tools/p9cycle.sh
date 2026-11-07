#!/bin/sh
# One mainline test cycle on the P9 Lite, driven from the Mac (phone on Mac USB).
#   r16 running -> reboot to fastboot -> flash test image -> boot it ->
#   wait for the test kernel to return to fastboot (p9test reboots there) ->
#   flash r16 back -> boot r16 -> save /sys/fs/pstore/console-ramoops-0
# Usage: p9cycle.sh <test-boot.img> <label>
set -u
IMG=$1; LABEL=${2:-test}
HERE=$(cd "$(dirname "$0")" && pwd)
FB="$HOME/p9lite-tools-venv/bin/python $HERE/p9fastboot.py"
R16=$HOME/p9lite-backups/boot-r16-nft.img
PHONE=user@192.168.2.50
LOGDIR=$HERE/../k7/logs; mkdir -p "$LOGDIR"
LOG=$LOGDIR/$(date +%Y%m%d-%H%M%S)-$LABEL.txt
ts() { date +%T; }

if ! $FB devices | grep -q fastboot; then
  echo "$(ts) rebooting r16 into fastboot"
  ssh -o ConnectTimeout=8 -o ServerAliveInterval=2 -o ServerAliveCountMax=3 $PHONE 'sync; sudo python3 -c "import ctypes,os; os.sync(); ctypes.CDLL(None).syscall(142, 0xfee1dead, 672274793, 0xA1B2C3D4, b\"bootloader\")"' >/dev/null 2>&1
  $FB wait 90 || exit 1
fi
echo "$(ts) flashing $IMG"; $FB flash boot "$IMG" || exit 1
$FB reboot; T0=$(date +%s); sleep 8
echo "$(ts) test kernel booting, waiting for it to return to fastboot"
if $FB wait 240; then
  echo "$(ts) back in fastboot after $(( $(date +%s) - T0 ))s"
else
  echo "$(ts) NOT back after 150s -> hold Volume Down (or Vol Down + Power) on the phone"
  $FB wait 600 || exit 1
fi
echo "$(ts) restoring r16"; $FB flash boot "$R16" && $FB reboot
# the test kernel presets "reboot to fastboot" in the PMIC; the bootloader honours it once more, so reboot again if it lands in fastboot
sleep 5; if $FB wait 45 >/dev/null 2>&1; then echo "$(date +%T) sticky fastboot flag, rebooting again"; $FB reboot; fi
for i in $(seq 1 40); do sleep 5; ping -c1 -t1 192.168.2.50 >/dev/null 2>&1 && break; done; sleep 5
ssh -o ConnectTimeout=10 $PHONE 'sudo cat /sys/fs/pstore/console-ramoops-0 2>/dev/null' > "$LOG"
echo "$(ts) r16 up; log: $LOG ($(wc -l < "$LOG") lines)"
