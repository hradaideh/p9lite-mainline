#!/bin/sh
# Watch the phone after a reboot: report whether it lands in fastboot or comes up on Wi-Fi (r16).
# Usage: p9wait-r16.sh [seconds]
HERE=$(cd "$(dirname "$0")" && pwd)
PY="$HOME/p9lite-tools-venv/bin/python"
N=${1:-60}
end=$(( $(date +%s) + N ))
while [ "$(date +%s)" -lt "$end" ]; do
  fb=$($PY "$HERE/p9fastboot.py" devices)
  if ping -c1 -t1 192.168.2.50 >/dev/null 2>&1; then w=UP; else w=down; fi
  echo "$(date +%T) fastboot=[$fb] wifi=$w"
  [ "$w" = UP ] && exit 0
  sleep 4
done
exit 1
