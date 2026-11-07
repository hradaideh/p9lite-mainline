# postmarketOS packages for the mainline kernel

| Package | What it ships |
|---|---|
| `linux-huawei-venus-mainline` | `/boot/vmlinuz` (7.x Image behind the mkstub branch), modules incl. Hi1102 `extra/plat.ko`, `extra/wifi.ko`. Provides/replaces `linux-huawei-venus`, so `device-huawei-venus` stays satisfied. |
| `p9lite-mainline` | `/etc/deviceinfo` (cmdline `console=tty0 panic=10 p9test.prod=1 p9test.sdio_prep=1 p9early`, `deviceinfo_flash_kernel_on_update="true"`), `/etc/local.d/p9-boot-ok.start`, `/etc/init.d/hisi-wifi`, `/etc/nftables.d/60_homeassistant.nft`. |

Repo on the phone: `/var/lib/p9repo` (listed in `/etc/apk/repositories`), signed with the key in the
build container (`/work/abuild-keys/p9lite.rsa`, never in git; public half in `/etc/apk/keys/p9lite.rsa.pub`).

## How an update reaches the boot partition
`apk upgrade` -> postmarketos-mkinitfs trigger -> new `/boot/initramfs` -> boot-deploy builds `/boot/boot.img`
from `/boot/vmlinuz` + deviceinfo offsets/cmdline -> because `deviceinfo_flash_kernel_on_update="true"` it
`dd`s the image to `PARTLABEL=boot`. The same happens on any other mkinitfs run (e.g. a postmarketOS upgrade
of mkinitfs or a hook), so every regular system upgrade keeps the boot partition in sync.

## Releasing a new kernel
1. In p9build: build `/work/out7prod` (k7/mac7prod.sh or incremental kbuild) and the Hi1102 modules (wifi-inventory.sh with `O=/work/out7prod`).
2. Bump `pkgver`/`pkgrel` in `linux-huawei-venus-mainline/APKBUILD`, copy `packaging/` to `/work/packaging`.
3. `sh /work/packaging/build-kernel-artifacts.sh && sh /work/packaging/build-packages.sh`
4. On the Mac: `tools/p9-publish-repo.sh`, then on the phone `sudo apk upgrade` and `sudo reboot`.

A kernel that fails to boot lands in fastboot by itself (p9early crash marker, p9test boot guard).
Roll back from fastboot by flashing the previous `/boot/boot.img` copy, or `~/p9lite-backups/boot-r16-nft.img`;
on the phone, `apk add linux-huawei-venus-mainline=<old version>` (old apks stay in the repo).

Escape to fastboot from a running system: `echo 0 > /sys/module/p9test/parameters/boot_ok; echo 1 > /sys/module/p9test/parameters/restart_now`.
