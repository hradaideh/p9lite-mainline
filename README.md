# Mainline Linux on the Huawei P9 lite (hi6250)

Mainline Linux **7.3.1** running postmarketOS on a Huawei P9 lite (VNS-L21, Kirin 650 / hi6250) that works
as a small home server (Docker, Home Assistant, nginx) over its own Hi1102 Wi-Fi. The kernel ships as a
postmarketOS package: `apk upgrade` rebuilds the boot image and flashes it to the boot partition.

Write-up: [blog.radaideh.info](https://blog.radaideh.info/blog/huawei-p9-lite-mainline-linux/).

## What works

| Area | State |
|---|---|
| Boot, 8 cores, 2 GB RAM, eMMC (sdhci-arasan) | works |
| Hi1102 Wi-Fi (vendor driver ported to 7.x) | scan, WPA2, DHCP/static IP |
| USB gadget (configfs NCM/RNDIS) | works |
| Docker (cgroup v1), iptables legacy + nftables, WireGuard, TUN | works |
| postmarketOS initramfs + OpenRC userspace | works, packaged |
| Display, battery charger, thermal/cpufreq, real Wi-Fi MAC from NVE | not yet |

## Layout

| Path | What |
|---|---|
| `k7/p9test.c` | Built-in board helper: SP805 watchdog feeding, eMMC/USB/SDIO bring-up fix-ups, reboot reasons, the boot guard and crash marker (below), kernel log into the vendor ramoops zone, battery readout. |
| `k7/p9min.config`, `p9wifi.config`, `p9prod.config` | Config fragments merged onto `allnoconfig` (`k7/mac7prod.sh`). |
| `k7/0001-*.patch`, `k7/0002-init-env-limit-128.patch` | Kernel patches. |
| `k7/hi1102-port/` | Port of Huawei's Hi1102 (Hi110x) Wi-Fi driver from the vendor 4.4 tree to 7.x. |
| `k7/mkstub.py` | Prepends a 1.5 MiB branch stub so the bootloader's fixed 0x480000 load puts the real Image 2 MiB-aligned. |
| `packaging/` | APKBUILDs for `linux-huawei-venus-mainline` and `p9lite-mainline`, build and publish scripts. See `packaging/README.md`. |
| `tools/` | `p9fastboot.py` (pure-Python fastboot over libusb), boot-image builders, test-cycle scripts. |
| `k7/*-plan.md` | Test plans and findings, in the order they happened. |

## Things that cost days (so they don't cost you)

- **`CONFIG_INIT_ENV_ARG_LIMIT=32` panics the kernel before any initcall.** The Huawei bootloader appends ~31
  dot-less `key=value` parameters (`boardid=`, `himntn=`, `TP_COLOR=` ...). The vendor kernel consumes them;
  mainline hands them to init as environment variables. A few more parameters (postmarketOS adds three) and
  `start_kernel` panics with "Too many boot env vars" — no console, no log, just the bootloader watchdog.
  Raise the limit (`k7/0002-init-env-limit-128.patch`).
- **`console=ttyS0` from the bootloader matches nothing on 7.x** (the UARTs are `ttyAMA*`), so PID 1 starts without
  stdin/stdout. A busybox `/init` does not care; the postmarketOS init dies. Add `console=tty0`.
- **Huawei boot-fail mode.** The bootloader keeps a boot keypoint in PMIC HRST_REG1 (`0xFFF34630`); stock Android
  sets 250 when boot completes. Any reset before that (watchdog, panic, thermal) counts as a boot failure, and a
  few of them send the phone into eRecovery. The records are in the `bootfail_info` partition (header `BFIX`,
  4 KiB members: RTC, errno, stage) — errno `0x03000003` is `KERNEL_AP_WDT`, stage `0x02000004` is
  `BL2_STAGE_END`. Never put a custom image into `recovery2`; stock eRecovery's "Reboot" is what clears the mode.
- The 4.4 kernel never loaded the postmarketOS nftables ruleset, so the firewall was effectively open. 7.x loads it
  (input policy drop); open the ports you need explicitly.

## Recovery net (p9test)

- `p9early` (a cmdline flag, handled in `parse_early_param`): writes boot keypoint 250 straight away and sets a crash
  marker in RAM that survives a warm reset. A boot that finds the marker still set restarts straight to fastboot and
  leaves the dead boot's kernel log in place for the next kernel to read (`/sys/fs/pstore/console-ramoops-0` on the
  vendor kernel).
- `p9test.prod=1`: every reset goes to fastboot until userspace writes `boot_ok=1` (`/etc/local.d/p9-boot-ok.start`
  after dockerd is up); no `boot_ok` within `boot_deadline` (600 s) also restarts to fastboot. A panic saves the log.
  Soft and hard (buddy) lockup detectors panic. A shutdown stuck for 30 s is forced through.
- Escape a running system to fastboot: `echo 0 > /sys/module/p9test/parameters/boot_ok; echo 1 > /sys/module/p9test/parameters/restart_now`.

## Building

The kernel is cross-built in an Alpine aarch64 container (`p9build`, `/work`): Linux 7.3.1 source, the vendor
4.4 tree (for Hi1102 headers), then `k7/mac7prod.sh`, `hi1102-port/wifi-inventory.sh` with `O=/work/out7prod`,
and the packaging scripts. Details and the release procedure: `packaging/README.md`.

## License

GPL-2.0 (kernel patches, p9test, the Hi1102 port). The Hi1102 driver itself is Huawei's GPL-2.0 code from the
P9 lite kernel source release.
