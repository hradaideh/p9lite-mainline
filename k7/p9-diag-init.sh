#!/bin/busybox sh
# /init for P9 Lite mainline DIAGNOSTICS on the production kernel (no g_ether):
# busybox userspace + remote shell over USB if usb0 exists, else over Wi-Fi (192.168.2.50, telnet 23 / nc 2323)
/bin/busybox --install -s /bin
export PATH=/bin
mount -t proc proc /proc
mount -t sysfs sys /sys
mount -t devtmpfs dev /dev 2>/dev/null
mkdir -p /dev/pts /tmp /var/lib/misc /var/run /var/log /mnt /etc
mount -t devpts devpts /dev/pts
log() { echo "p9init: $*" > /dev/kmsg; }
log "busybox userspace up on $(uname -r)"
echo 1 > /sys/module/p9test/parameters/keepalive 2>/dev/null && log "watchdog keepalive set"
for i in $(seq 1 30); do [ -e /sys/class/net/usb0 ] && break; sleep 1; done
if [ -e /sys/class/net/usb0 ]; then
  ip link set lo up
  ip link set usb0 up
  ip addr add 172.16.42.1/24 dev usb0
  ip addr add 169.254.42.1/16 dev usb0   # reachable from a Mac that fell back to link-local
  touch /var/lib/misc/udhcpd.leases
  udhcpd -S /etc/udhcpd.conf
  syslogd -C64 2>/dev/null
  telnetd -l /bin/sh
  ( while true; do nc -l -p 2323 -e /bin/sh; done ) &
  log "usb0 up $(cat /sys/class/net/usb0/address) 172.16.42.1, udhcpd + telnetd:23 + nc-shell:2323"
else
  log "usb0 did not appear: bringing up Wi-Fi for the remote shell"
  ip link set lo up
  p9wifi all > /tmp/wifi.log 2>&1 && p9wifi connect >> /tmp/wifi.log 2>&1
  syslogd -C64 2>/dev/null
  telnetd -l /bin/sh
  ( while true; do nc -l -p 2323 -e /bin/sh; done ) &
  log "Wi-Fi shell: $(tail -1 /tmp/wifi.log)"
fi
while true; do sleep 3600; done
