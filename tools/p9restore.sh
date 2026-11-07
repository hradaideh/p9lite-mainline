#!/bin/sh
# Wait for the phone in fastboot, flash r16 back, boot it and save the test kernel's log.
# Usage: p9restore.sh <label> [wait-seconds]
LABEL=${1:-test}; WAIT=${2:-400}
HERE=$(cd "$(dirname "$0")" && pwd)
FB="$HOME/p9lite-tools-venv/bin/python $HERE/p9fastboot.py"
LOGDIR=$HERE/../k7/logs; mkdir -p "$LOGDIR"
LOG=$LOGDIR/$(date +%Y%m%d-%H%M%S)-$LABEL.txt
$FB wait "$WAIT" || { echo "phone not in fastboot - hold Volume Down (or Vol Down + Power)"; $FB wait 600 || exit 1; }
echo "$(date +%T) in fastboot, restoring r16"
$FB flash boot "$HOME/p9lite-backups/boot-r16-nft.img" && $FB reboot
# the test kernel presets "reboot to fastboot" in the PMIC; the bootloader honours it once more, so reboot again if it lands in fastboot
sleep 5; if $FB wait 45 >/dev/null 2>&1; then echo "$(date +%T) sticky fastboot flag, rebooting again"; $FB reboot; fi
UP=; for i in $(seq 1 40); do sleep 5; ping -c1 -t1 192.168.2.50 >/dev/null 2>&1 && { UP=1; break; }; done; sleep 5
# not on LAN -> usually Huawei boot-fail mode (it boots recovery2 = eRecovery): pick "Reboot" there to clear it
[ -n "$UP" ] || { echo "$(date +%T) r16 NOT on LAN - check the screen (eRecovery menu -> Reboot)"; exit 1; }
ssh -o ConnectTimeout=10 user@192.168.2.50 'sudo cat /sys/fs/pstore/console-ramoops-0 2>/dev/null' > "$LOG"
echo "$(date +%T) r16 up; log: $LOG ($(wc -l < "$LOG") lines)"
