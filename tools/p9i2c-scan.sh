#!/bin/sh
# Scan i2c4 with the /dev/mem DesignWare helper: print addresses that ACK.
a=8
while [ $a -le 119 ]; do
	o=$(python3 /tmp/p9i2c-mem.py get $a 0 1 2>&1)
	case "$o" in 00:*) printf '0x%02x ' $a ;; esac
	a=$((a + 1))
done
echo
echo scan-done
