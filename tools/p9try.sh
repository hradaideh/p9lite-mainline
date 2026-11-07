#!/bin/sh
# Flash a test image (phone must be in fastboot or on r16), boot it, and report what happened:
#   shell    - USB shell at 172.16.42.1 answers (test kernel is up)
#   fastboot - test kernel froze/rebooted and the watchdog/restart handler brought it to fastboot
# Usage: p9try.sh <img> [max-seconds]
IMG=$1; MAX=${2:-240}
HERE=$(cd "$(dirname "$0")" && pwd)
FB="$HOME/p9lite-tools-venv/bin/python $HERE/p9fastboot.py"
if ! $FB devices | grep -q fastboot; then
  ssh -o ConnectTimeout=8 -o ServerAliveInterval=2 -o ServerAliveCountMax=3 user@192.168.2.50 'sync; sudo python3 -c "import ctypes,os; os.sync(); ctypes.CDLL(None).syscall(142, 0xfee1dead, 672274793, 0xA1B2C3D4, b\"bootloader\")"' >/dev/null 2>&1
  $FB wait 120 || exit 1
fi
$FB flash boot "$IMG" || exit 1
$FB reboot
T0=$(date +%s); echo "$(date +%T) booting $IMG"
sleep 10
# the bootloader may honour a leftover "fastboot" flag once
if $FB devices | grep -q fastboot; then echo "$(date +%T) sticky flag, rebooting again"; $FB reboot; sleep 10; fi
R=timeout
end=$(( T0 + MAX ))
while [ "$(date +%s)" -lt "$end" ]; do
  if ping -c1 -t1 172.16.42.1 >/dev/null 2>&1; then R=shell; break; fi
  if $FB devices | grep -q fastboot; then R=fastboot; break; fi
  sleep 3
done
echo "$(date +%T) result=$R after $(( $(date +%s) - T0 ))s"
