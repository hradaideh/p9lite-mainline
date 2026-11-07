#!/bin/sh
# Switch from a running test kernel to a new test image and run the SDIO/Wi-Fi bring-up trigger.
# Usage: p9sdio-test.sh <img>
HERE=$(cd "$(dirname "$0")" && pwd)
printf 'sync; reboot -f\n' | nc -w 3 172.16.42.1 2323 >/dev/null 2>&1
sh "$HERE/p9try.sh" "$1" 240 | tail -2
printf 'mount -t debugfs none /sys/kernel/debug; (echo 1 > /sys/kernel/debug/p9test/sdio) & sleep 8; dmesg | grep -E "p9dbg|volts|pinctrl default|mmc1|sdio card|hi1102" | head -14; for d in /sys/bus/sdio/devices/*; do echo $d vendor=$(cat $d/vendor 2>/dev/null) device=$(cat $d/device 2>/dev/null) class=$(cat $d/class 2>/dev/null); done; exit\n' | nc -w 25 172.16.42.1 2323
