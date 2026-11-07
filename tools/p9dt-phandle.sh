#!/bin/sh
# p9dt-phandle.sh <hex phandle>... : print the live-DT node for each phandle with its properties
cd /proc/device-tree
for want in "$@"; do
	want=$(printf '%08x' $((0x$want)))
	for f in $(find . -name phandle); do
		[ "$(hexdump -ve '1/1 "%02x"' $f)" = "$want" ] || continue
		d=$(dirname $f); echo "== $want $d"
		for p in $d/*; do
			[ -f "$p" ] && echo "  $(basename $p): $(hexdump -ve '1/1 "%02x"' $p | head -c 96)"
		done
		pd=$(dirname $d); echo "  parent $(basename $pd) reg=$(hexdump -ve '1/1 "%02x"' $pd/reg 2>/dev/null) compat=$(tr '\0' ',' < $pd/compatible 2>/dev/null)"
	done
done
