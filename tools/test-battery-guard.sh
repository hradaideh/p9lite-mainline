#!/bin/sh
# Self-check for phone-files/usr/local/bin/p9-battery-guard (runs on the Mac, never flashes anything).
G=$(cd "$(dirname "$0")/.." && pwd)/phone-files/usr/local/bin/p9-battery-guard
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
run() { echo "$1" > "$T/bat"; P=$T/bat LOG=$T/log R16=$T/none INTERVAL=0.05 sh -x "$G" 2> "$T/trace" & p=$!; sleep 1; kill $p; wait $p 2>/dev/null; }
run "0 0 bad-read";               ! grep -q "not flashing" "$T/trace" || { echo "FAIL: acted on a bad read"; exit 1; }
run "3500000 -100000 low";        grep -q "not flashing" "$T/trace"   || { echo "FAIL: low battery not detected"; exit 1; }
run "4300000 50000 ok";           ! grep -q "not flashing" "$T/trace" || { echo "FAIL: acted on a good battery"; exit 1; }
echo "battery guard OK"
