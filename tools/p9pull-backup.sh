#!/bin/bash
# Pull a full rollback set from the running phone to the Mac. Nothing large is written on the phone.
set -euo pipefail
PHONE=user@192.168.2.50
D=${1:-$HOME/p9lite-backups/2026-11-06-running-state}
mkdir -p "$D/partitions" "$D/meta"
cd "$D"

echo "== rootfs tar (already built on phone) =="
R=/tmp/rootfs-2026-11-06.tar.gz
if ssh $PHONE "test -f $R"; then
  remote=$(ssh $PHONE "sudo sha256sum $R" | cut -d' ' -f1)
  scp -q $PHONE:$R rootfs-2026-11-06.tar.gz
  local=$(shasum -a 256 rootfs-2026-11-06.tar.gz | cut -d' ' -f1)
  [ "$remote" = "$local" ] || { echo "rootfs sha mismatch"; exit 1; }
  gzip -t rootfs-2026-11-06.tar.gz
  echo "$local  rootfs-2026-11-06.tar.gz" >> SHA256SUMS
  ssh $PHONE "sudo rm -f $R"
  echo "rootfs ok, removed from phone"
fi

echo "== metadata =="
ssh $PHONE 'sudo sfdisk -d /dev/mmcblk0' > meta/gpt-mmcblk0.sfdisk
ssh $PHONE 'sudo sfdisk -d /dev/loop0' > meta/loop0-userdata.sfdisk
ssh $PHONE 'sudo blkid' > meta/blkid.txt
ssh $PHONE 'cat /proc/cmdline; echo; uname -a; cat /etc/os-release' > meta/system.txt
ssh $PHONE 'sudo rc-update show -v' > meta/rc-update.txt
ssh $PHONE 'lsmod; echo; ip -d addr; ip route; echo; sudo nft list ruleset 2>&1' > meta/net-modules.txt
ssh $PHONE 'sudo dmesg' > meta/dmesg.txt
ssh $PHONE 'sudo docker ps -a --no-trunc; sudo docker images --digests' > meta/docker.txt

echo "== raw partitions (all except userdata) =="
ssh $PHONE 'for p in /sys/class/block/mmcblk0p*; do echo "$(basename $p) $(grep PARTNAME $p/uevent | cut -d= -f2)"; done' |
while read dev name; do
  [ "$name" = userdata ] && continue
  out="partitions/$(printf %02d ${dev#mmcblk0p})-$name.img.gz"
  [ -s "$out" ] && continue
  # read raw on phone, hash both the raw stream and the compressed file on the Mac
  rsha=$(ssh -n $PHONE "sudo sha256sum /dev/$dev" | cut -d' ' -f1)
  ssh -n $PHONE "sudo dd if=/dev/$dev bs=4M status=none" | tee >(shasum -a 256 | cut -d' ' -f1 > "$out.rawsha") | gzip -6 > "$out"
  [ "$rsha" = "$(cat "$out.rawsha")" ] || { echo "MISMATCH $name"; exit 1; }
  echo "$rsha  $dev-$name (raw)" >> partitions/RAW-SHA256SUMS
  rm "$out.rawsha"
  echo "  $name ok"
done
shasum -a 256 partitions/*.img.gz >> SHA256SUMS
echo "ALL DONE"; du -sh "$D"
