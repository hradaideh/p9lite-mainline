# 7.3.1 as the production kernel — plan

Goal: the phone runs 7.3.1 day to day (HA, nginx, Wi-Fi, ssh). r16 is the fallback only after every 7.3.1 option
is exhausted, and is restored automatically if the battery is at risk.

## Inventory: what r16 gives production, and the 7.3.1 answer
| Need | r16 | 7.3.1 plan | Phase |
|------|-----|-----------|-------|
| Rootfs | pmOS initramfs, loop subpartitions in userdata | reuse r16's initramfs unchanged; kernel: loop (+partscan, direct-io), ext4/ext2, configfs, devtmpfs | 1 |
| Reboot/panic | normal boot | p9test `prod=1`: reason from cmd (`bootloader`=0x01, else COLDBOOT 0x10); no auto-reboot report; keepalive on; early_reason off | 1 |
| Watchdog | vendor feeds SP805 | p9test hrtimer feeds it (keepalive=1) | 1 |
| Wi-Fi | hisi-wifi | same service + 7.x prelude: p9test SDIO power-up, insmod plat/wifi from /lib/modules/$(uname -r)/extra | 1 |
| Docker (HA host-net, nginx bridge, mesh tun) | iptables legacy, cgroup v1 | namespaces, cgroups incl. v1 memcg/cpuset, overlayfs, veth, bridge(+netfilter), x_tables legacy + nf_tables (inet/fib/nat), tun, wireguard | 1 |
| USB ssh fallback (172.16.42.1) | configfs gadget | USB_CONFIGFS (+RNDIS/NCM/ECM), g_ether off | 1 |
| Battery charging | vendor Hi6523 charger + Hi6555 gauge | no mainline driver: charger runs on hardware defaults. p9test exposes gauge voltage/current; `p9-battery-guard` logs every minute and, below 3.65 V, writes r16 to boot and reboots | 1 |
| Thermal / cpufreq | vendor | none in mainline (CPU stays at bootloader clocks); log temperatures if a sensor is reachable | 2 |
| LCD dashboard | hisifb /dev/fb0 | simplefb on the bootloader's framebuffer | 2 |
| RTC | vendor PMIC RTC | none; chronyd sets time from network | — |

## Phase 1 steps
1. Kernel `out7prod` = p9min + p9wifi + `k7/p9prod.config`; p9test `prod` + `battery` params. QEMU boot check.
2. Rootfs (reversible, r16 unaffected; full rootfs backup exists): modules to /lib/modules/7.3.1/extra + depmod;
   hisi-wifi 7.x prelude (guarded by `uname -r`); p9-battery-guard service (7.x only); r16 image copy at
   /root/boot-r16.img for the guard.
3. Boot image `boot-prod-7.3.1.img` = stubbed 7.3.1 Image + r16 initramfs + r16 cmdline + `p9test.prod=1`.
4. Flash via fastboot (`reboot bootloader` from r16). Checks, in order: USB ssh 172.16.42.1 -> Wi-Fi .50 ->
   docker HA/nginx -> battery readings -> `reboot` returns to 7.3.1 (not fastboot).
   Escape at any point: `reboot bootloader` (prod) / `restart_now` (test) -> fastboot -> fix -> reflash.
   Never: watchdog starve, custom images in recovery2.
5. Soak: battery log for hours. Charging or flat at full -> stay. Discharging -> guard reverts; then find a way
   to drive the Hi6523 (I2C) before retrying.

## 2026-11-07: recoverable test loop (no more eRecovery)
Why the phone kept landing in eRecovery: Huawei's bootloader keeps a boot keypoint in PMIC HRST_REG1
(0xFFF34630, `hisi_bootup_keypoint.c`); stock Android sets it to 250 (boot success). A reset before 250 with a
non-fastboot reason is a boot failure; a few of them -> boot-fail mode -> recovery2 (eRecovery). In prod mode a
panic wrote COLDBOOT, so a failing kernel rebooted into itself until BFM tripped.

Why 7.3.1 + pmOS failed at all (found with the Wi-Fi diag shell): the bootloader appends `console=ttyS0`, which
matches no UART on 7.x ("unable to open an initial console"); pmOS init (setup_log `exec 3>&1`) dies -> panic.
Fix: `console=tty0` on our cmdline. Also: keep r16's initramfs as XZ (the gzip re-pack was larger).
The full r16 userspace (udev, every OpenRC service, docker, HA 200) was verified on 7.3.1 by hand.

p9test boot guard (prod): reason preset BOOTLOADER until userspace writes `boot_ok=1`
(phone-files/etc/local.d/p9-boot-ok.start, after dockerd is up); panic notifier -> fastboot + log saved;
`boot_deadline` (600 s) without boot_ok -> fastboot. boot_ok writes keypoint 250 and switches to COLDBOOT.
Kernel: soft/hard (buddy) lockup detectors panic, hung-task detector reports.

Test order (each failure ends in fastboot, log readable from r16 as /sys/fs/pstore/console-ramoops-0):
1. r16 back on boot (HA up); install p9-boot-ok.start + rebuilt hi1102 modules.
2. boot-guard-test.img (diag initrd, prod=1): `echo c > /proc/sysrq-trigger` -> must land in fastboot; r16 shows the panic log.
3. boot-prod-guard.img: success = HA 200 + boot_ok; failure = fastboot by itself, read the log, fix, repeat.

## 2026-11-07 result: 7.3.1 in production (build #6, boot-prod-final.img)
Root cause of every failed pmOS boot: `CONFIG_INIT_ENV_ARG_LIMIT=32`. The Huawei bootloader appends ~31 dot-less
`key=value` params (boardid=, himntn=, TP_COLOR=, ...) that 7.x does not consume, so they become init env vars;
our three `pmos_*` params pushed it past 32 -> `panic("Too many boot env vars")` in start_kernel, before any
initcall -> bootloader AP watchdog -> boot-fail mode -> eRecovery. Found by bisection: the diag ramdisk with the
production cmdline died the same way; the ramdisk padded to 7.9 MB booted. Fix: k7/0002-init-env-limit-128.patch.
Decoder for the evidence: `bootfail_info` partition (BFIX header, 4 KiB records: rtc, errno, stage);
errno 0x03000003 = KERNEL_AP_WDT, stage 0x02000004 = BL2_STAGE_END (kernel never advanced the keypoint).

Also needed: `console=tty0` (bootloader's console=ttyS0 matches nothing on 7.x), r16 initramfs kept as XZ,
nftables rule for 8123 (phone-files/etc/nftables.d/60_homeassistant.nft: r16's 4.4 kernel never loaded the
ruleset, 7.x does and its input policy is drop).

Recovery net (p9test), all verified on hardware:
- `p9early` (parse_early_param): keypoint 250 at once + crash marker at 0x348FFFF0; a boot that finds the marker
  still BOOTING restarts straight to fastboot and keeps the dead boot's log (watchdog-starve test: fastboot in 34 s).
- prod: resets go to fastboot until `boot_ok` (local.d/p9-boot-ok.start after dockerd); 600 s deadline;
  panic notifier saves log; soft/hard lockup detectors panic; shutdown stuck > 30 s -> forced restart.
- After boot_ok a plain `reboot` returns to 7.3.1 with HA up in ~65 s (tested).
Escape to fastboot from production: `echo 0 > .../boot_ok; echo 1 > .../restart_now`.
Thermal ruled out: 8 cores at 100 % for 10 min on 7.3.1 without a reset.
