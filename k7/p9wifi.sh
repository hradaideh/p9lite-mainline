#!/bin/sh
# Staged Hi1102 Wi-Fi bring-up on the 7.x test kernel, run from the USB shell.
# Usage: p9wifi [mount|sdio|load|init|scan|connect|all]   (each step is idempotent-ish; default all but connect)
# Nothing here writes to the eMMC: the production rootfs is mounted ro,noload.
R=/mnt/root
log() { echo "p9wifi: $*"; echo "p9wifi: $*" > /dev/kmsg; }
die() { log "FAILED: $*"; exit 1; }
waitfor() { i=0; while [ ! -e "$1" ] && [ $i -lt "$2" ]; do sleep 1; i=$((i+1)); done; [ -e "$1" ]; }

step_mount() {
	grep -q " $R " /proc/mounts && { log "rootfs already mounted"; return 0; }
	dev=
	for u in /sys/class/block/*/uevent; do grep -qx PARTNAME=userdata "$u" && dev=$(basename "$(dirname "$u")"); done
	[ -n "$dev" ] || die "userdata partition not found"
	losetup -P -r /dev/loop0 "/dev/$dev" || die "losetup $dev"
	waitfor /dev/loop0p2 5 || die "loop0p2 missing"
	mkdir -p $R /vendor /lib/firmware /data
	mount -t ext4 -o ro,noload /dev/loop0p2 $R || die "mount rootfs"
	mount --bind $R/vendor /vendor && mount --bind $R/lib/firmware /lib/firmware && mount -t tmpfs data /data || die "binds"
	# firmware cfg names /system/vendor/firmware/*; the efuse dump goes to /data/misc/wifi
	mkdir -p /system /data/misc/wifi && ln -sfn /vendor /system/vendor
	log "rootfs ($dev) mounted ro,noload; /vendor /lib/firmware bound; /data is tmpfs"
}

step_sdio() {
	grep -q debugfs /proc/mounts || mount -t debugfs debugfs /sys/kernel/debug
	ls /sys/bus/sdio/devices/ 2>/dev/null | grep -q . && { log "sdio card already present"; return 0; }
	echo 1 > /sys/kernel/debug/p9test/sdio || die "p9test sdio bring-up"
	i=0; while ! grep -qs 0x0296 /sys/bus/sdio/devices/*/vendor && [ $i -lt 15 ]; do sleep 1; i=$((i+1)); done
	grep -qs 0x0296 /sys/bus/sdio/devices/*/vendor || die "Hi1102 (0296) did not enumerate"
	log "Hi1102 enumerated: $(cat /sys/bus/sdio/devices/*/device | tr '\n' ' ')"
}

step_load() {
	for m in plat wifi; do
		grep -q "^$m " /proc/modules && continue
		insmod /p9/$m.ko || die "insmod $m"
		log "$m.ko loaded"
	done
}

step_init() {
	waitfor /sys/hisys/boot/plat 10 || die "/sys/hisys/boot/plat missing (board probe failed? see dmesg)"
	[ "$(cat /sys/hisys/boot/plat)" = running ] || echo init > /sys/hisys/boot/plat
	log "plat: $(cat /sys/hisys/boot/plat)"
	# wifi init after a failed plat init oopses in the driver's error path (seen under QEMU)
	[ "$(cat /sys/hisys/boot/plat)" = running ] || die "plat init did not reach 'running'; not starting wifi"
	[ "$(cat /sys/hisys/boot/wifi)" = running ] || echo init > /sys/hisys/boot/wifi
	log "wifi: $(cat /sys/hisys/boot/wifi)"
	waitfor /sys/class/net/wlan0 20 || die "wlan0 did not appear"
	ip link set wlan0 up || die "wlan0 up"
	log "wlan0 up, mac $(cat /sys/class/net/wlan0/address)"
}

chroot_prep() {
	grep -q " $R/proc " /proc/mounts && return 0
	mount --bind /proc $R/proc && mount --bind /sys $R/sys && mount --bind /dev $R/dev &&
	mount -t tmpfs run $R/run && mount -t tmpfs tmp $R/tmp || die "chroot mounts"
}

step_scan() {
	chroot_prep
	chroot $R /usr/bin/iw dev wlan0 scan > /tmp/scan.txt 2>&1 || die "scan: $(head -3 /tmp/scan.txt)"
	log "scan ok: $(grep -c '^BSS' /tmp/scan.txt) BSS: $(grep 'SSID:' /tmp/scan.txt | sed 's/.*SSID: //' | sort -u | tr '\n' ',' | cut -c1-200)"
}

# Connects with the phone's own wpa_supplicant.conf. Only run when r16 is NOT on the network
# (it is not while this kernel runs) because it takes the same static IP.
step_connect() {
	chroot_prep
	chroot $R /usr/bin/wpa_supplicant -B -D nl80211 -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant.conf -P /run/wpa.pid || die "wpa_supplicant"
	i=0; while ! chroot $R /usr/bin/wpa_cli -i wlan0 status 2>/dev/null | grep -q wpa_state=COMPLETED && [ $i -lt 30 ]; do sleep 1; i=$((i+1)); done
	chroot $R /usr/bin/wpa_cli -i wlan0 status | grep -q wpa_state=COMPLETED || die "association: $(chroot $R /usr/bin/wpa_cli -i wlan0 status | grep wpa_state)"
	ip addr add 192.168.2.50/24 dev wlan0; ip route replace default via 192.168.2.1 dev wlan0
	ping -c3 -W2 192.168.2.1 >/dev/null && log "CONNECTED: 192.168.2.50, gateway answers" || die "associated but gateway does not answer"
}

case "${1:-all}" in
	all) step_mount && step_sdio && step_load && step_init && step_scan && log "ALL STEPS OK (run 'p9wifi connect' to associate)";;
	mount|sdio|load|init|scan|connect) step_$1;;
	*) echo "usage: p9wifi [mount|sdio|load|init|scan|connect|all]"; exit 2;;
esac
