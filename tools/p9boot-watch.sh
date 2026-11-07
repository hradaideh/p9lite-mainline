#!/bin/sh
# Flash a test image, boot it, and watch the Mac for a USB network interface from the phone.
# Usage: p9boot-watch.sh <test-boot.img> [watch-seconds]
IMG=$1; WATCH=${2:-90}
HERE=$(cd "$(dirname "$0")" && pwd)
FB="$HOME/p9lite-tools-venv/bin/python $HERE/p9fastboot.py"
before=$(ifconfig -l)
if ! $FB devices | grep -q fastboot; then
  ssh -o ConnectTimeout=8 -o ServerAliveInterval=2 -o ServerAliveCountMax=3 user@192.168.2.50 'sync; sudo python3 -c "import ctypes,os; os.sync(); ctypes.CDLL(None).syscall(142, 0xfee1dead, 672274793, 0xA1B2C3D4, b\"bootloader\")"' >/dev/null 2>&1
  $FB wait 120 || exit 1
fi
$FB flash boot "$IMG" || exit 1
$FB reboot
echo "$(date +%T) booting test image, watching USB for ${WATCH}s"
end=$(( $(date +%s) + WATCH ))
while [ "$(date +%s)" -lt "$end" ]; do
  sleep 2
  now=$(ifconfig -l)
  if [ "$now" != "$before" ]; then
    echo "$(date +%T) new network interface(s): $now"
    break
  fi
done
echo "--- USB devices on the Mac:"
ioreg -p IOUSB -l -w0 2>/dev/null | grep -E '"USB Product Name"|"idVendor"|"idProduct"' | paste - - - | tail -4
echo "--- interfaces with phone-side addresses:"
ifconfig | awk '/^[a-z]/{i=$1} /inet (172\.16\.42|169\.254)/{print i, $2}'
