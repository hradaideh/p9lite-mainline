# Huawei P9 Lite → Headless Linux Homelab Server

**Device:** Huawei P9 Lite (VNS-L21), Kirin 650 (hi6250), serial `BUC0216B05001378`
**Stock firmware at project start:** EMUI 5.0 / Android 7.0, build `VNS-L21C185B399`, security patch 2019-08-01, bootloader locked, `FBLOCK`/verified-boot GREEN, SIM carrier Orange JO.
**Goal:** replace Android entirely with native postmarketOS (mainline-ish Linux, not a chroot/LXC-on-Android hack), then turn it into a small always-on server (static IP, Docker, nginx, eventually Wi-Fi + Home Assistant).

This file is the single record of every phase, every real command/config that was confirmed to work, every dead end, and the current unresolved state — so the project can be picked up or rebuilt from scratch without re-discovering any of this.

---

## Phase 1 — Unlocking the bootloader (PotatoNV exploit)

Huawei stopped issuing official `fastboot oem unlock` codes for most devices around 2018, so the only way in is a known hardware-level exploit chain (PotatoNV) that works on this generation of Huawei/Honor Kirin SoCs. Standard "ask Huawei for a code" was not an option.

### Why this was needed
`fastboot oem get-bootinfo` / stock fastboot only exposes a crippled command set on a locked Huawei bootloader — there is no "enter unlock code" flow left for VNS-L21 on this firmware. PotatoNV instead drives the SoC's low-level **IDT boot-ROM/recovery USB interface** directly.

### Tools used
- **`PotatoNV-crossplatform`** (Python) and **`potatonv-csharp`** — both cloned locally into `~/p9lite-linux/`. The crossplatform Python port's `usrlock` module talks to the phone over what it expects to be a serial port, but on macOS/Linux the HiSilicon **IDT "USB SER" vendor-specific device (USB VID `0x12D1`, PID `0x3609`)** never gets a serial/cdc_acm driver bound (interface class is `0xff`, fully vendor-specific), so `pyserial`'s `connect_serial()` can never find it.
- **`runner/unlock_shim.py`** — a custom raw-`libusb`/`pyusb` bridge written specifically to solve the above: it reimplements the exact byte-level framing protocol (`usrlock/imageflasher.py`'s head/data/tail frames with a CRC-16 trailer, ACK byte `0xAA`) directly against the two bulk endpoints (`EP_OUT=0x01`, `EP_IN=0x81`) of the `12D1:3609` device, with no OS driver involved at all.

### How the unlock actually works (as implemented in `unlock_shim.py`)
1. **Hardware step (not automatable):** the phone is put into the IDT boot-ROM mode by shorting a test point on the board while powering on/connecting USB (standard Kirin "EDL-equivalent" entry), so it enumerates as `12D1:3609` instead of normal fastboot.
2. **Temporary bootloader upload** — two images from `PotatoNV-crossplatform/bootloaders/hisi65x_a/` are pushed over the raw USB bulk link, framed as above:
   - `xloader.img` → loaded at `0x00020000`
   - `fastboot.img` → loaded at `0x10000000`

   This temporary fastboot is **unlocked-by-default** (it's not the phone's real, signed bootloader — it only lives in RAM/boot-ROM context for this session) and is what makes the subsequent NVME writes possible.
3. **Device re-enumerates as normal fastboot**, and the script waits for it (`fastboot.Fastboot()` from the same repo).
4. **`write_nvme_full(fb_dev, key)`** — this is the actual unlock, and it is a reimplementation of the *original C# PotatoNV's* `Core.cs WriteNVME()`, because the Python `usrlock` port was **missing a critical first step** (documented directly in the shim's own docstring: a first attempt, "v1", completed with no errors but never actually unlocked the device, because it skipped this):
   - Read current `FBLOCK` state (`oem lock-state info` / `oem backdoor info`) for diagnostics only.
   - **Write `FBLOCK=1`** via `getvar:nve:FBLOCK@<1 byte>` (NVME property write) — note this is the *default/safe* value, i.e. this step does **not** disable the hardware watchdog/lock flag, it just re-asserts the normal state as a prerequisite the vendor code expects before the next writes are accepted. Falls back to `oem hwdog certify set <state>` / `oem backdoor set <state>` if the NVME write path fails.
   - **Write `WVLOCK`** = the raw 16-character unlock key, ASCII, via `getvar:nve:WVLOCK@<key>`.
   - **Write `USRKEY`** = SHA-256 digest of that same key, via `getvar:nve:USRKEY@<digest>`.
   - Each write's fastboot response must contain `"set nv ok"` or the script raises.
5. **Reboot.**
6. Finally, the **real, standard unlock command** is issued once the phone is back in its own normal (now-unlockable) fastboot:
   ```
   fastboot oem unlock NLYDI815YRQUUDUJ
   ```
   (this exact 16-character key is recorded in `~/.bash_history` on the control machine — it is this device's actual bootloader unlock key, derived from/used as the `WVLOCK`/`USRKEY` value above. **Keep this key** — it's what re-unlocks this specific phone if it's ever re-locked or wiped.)

### Verification artifacts kept
- `android-properties.txt` — full `getprop` dump taken while still on stock EMUI, for reference (model `HUAWEI VNS-L21`, `ro.boot.hardware=hi6250`, `ro.board.platform=hi6250`, `ro.oem_unlock_supported=1`, `ro.boot.flash.locked=1` at the time, `is_hisi_connectivity_chip=1`, wifi interface name `wlan0`, baseband `21.288.07.00.050`).
- `adb-devices.txt`, `fastboot-info.txt`, `fastboot-vars.txt`, `bootloader-info.txt`, `kernel.txt` (stock `4.1.18` kernel `/proc/cpuinfo` + `/proc/meminfo` + partition table — this is the **reference partition map** for `mmcblk0p1`–`p49`, useful if a partition ever needs to be identified/restored).
- `~/.bash_history` on the control Mac still has the literal commands run: `fastboot --version`, `fastboot devices`, `fastboot getvar product`, `fastboot oem get-bootinfo`, `fastboot oem unlock NLYDI815YRQUUDUJ`.

---

## Phase 2 — Installing native postmarketOS

With the bootloader unlocked, Android was wiped and replaced with **postmarketOS built from source via `pmbootstrap`**, targeting the (testing-tier) `huawei-venus` device port — *not* a chroot/proot-on-Android approach, a real standalone Linux rootfs flashed to the `boot`/system partitions.

Work on this phase, and all subsequent phases, was driven from a separate Linux machine referred to throughout as **"the Deck"** (reached over SSH as `deck@192.168.1.123` from the control Mac; also referenced in file paths as `~/p9lite-linux-deck/` on that machine), which hosted the actual `pmbootstrap` build environment (`~/p9lite-linux-deck/pmb-venv/`) and all kernel source/build trees. The Mac itself only ever talked to the phone over `fastboot`/the PotatoNV tooling and, later, `ssh user@172.16.42.1` once Linux was up.

Confirmed working end state:
- Device port: **`huawei-venus`** (pmaports `device/testing/linux-huawei-venus/`), kernel package **`linux-huawei-venus`**.
- The phone boots a **custom-built kernel** (not pmOS's stock package as-is) — the kernel config lives at `pmaports/device/testing/linux-huawei-venus/config-huawei-venus.aarch64` on the Deck, and was patched at least once in-session for a **`POSIX_MQUEUE` fix** required to get Docker's dependencies working (see Phase 4) — this is the `pkgrel-15` kernel referenced below.
- Build/flash cycle used: `~/p9lite-linux-deck/pmb-venv/bin/pmbootstrap` (note: **must use this full path** in non-interactive/non-login shells — the venv is not on `PATH` otherwise) → `pmbootstrap flasher flash_kernel` → **plain `fastboot`** (this device is NOT `heimall-bootimg`, so `--no-reboot` is rejected by `pmbootstrap flasher`; the device did not auto-reboot after flashing either, so a manual `fastboot reboot` was required every time).
- Known-good boot image preserved as a rollback target: `~/p9lite-backups/boot-known-good-pkgrel15.img` (32,282,624 bytes, `sha256:30d70138d54cfd169668fba24706bc78fee44da85aea2112a54f9687855d8e07`), copied from `~/.local/var/pmbootstrap/chroot_rootfs_huawei-venus/boot/boot.img` on the Deck. **If anything goes wrong with a future kernel rebuild, re-flash this exact file with `fastboot flash boot boot-known-good-pkgrel15.img` to get back to the last fully-confirmed-working state** (Docker+nginx working, static IP working, no wifi).

### Networking out of the box
*(Original state; Wi-Fi now works, see Phase 5.)* At this point the phone had **no working Wi-Fi** and **no ethernet**, so its only network path was **USB RNDIS** (`rndis0` on the phone side, enumerating as a USB Ethernet gadget on the host). postmarketOS's built-in `unudhcpd` boot service hands the phone a **fixed static IP of `172.16.42.1/16`** on every boot automatically — this is why the "static IP" part of the original ask was already satisfied by the stock pmOS RNDIS setup with zero extra configuration, confirmed stable across many reboots. The control side (Mac or Deck) sees the phone as a `enp...u1u3u1`-style RNDIS interface and reaches it at `172.16.42.1` over SSH (`ssh user@172.16.42.1`, confirmed in `~/.bash_history`).

~~The phone itself has no independent internet access~~ **Superseded by Phase 5:** the phone now has its own internet over Wi-Fi (`192.168.2.50` on `IOT`, default route via `192.168.2.1`). The old workaround was manual NAT (iptables MASQUERADE through the Deck), which did not persist across phone reboots; it's no longer needed.

---

## Phase 3 — Docker + nginx in bridge mode

This was the first explicit deliverable and is **fully working** as of the last verified test.

### The core problem
This phone's kernel (`4.4`-era HiSilicon tree) **cannot support cgroup v2 at all** — `CONFIG_CGROUP_BPF` doesn't exist anywhere in this kernel source tree, so cgroup v2 is not a "turn it on" problem, it's categorically unbuildable on this kernel. Meanwhile modern `runc` (1.5.2, what ships with recent Docker) hits an **unfixable Rust/`pathrs` panic on `/proc/thread-self`** on a kernel this old, regardless of cgroup version.

### The fix (confirmed working, currently deployed)
1. Force the whole system to classic **cgroup v1** ("legacy" hierarchy):
   ```
   # /etc/rc.conf
   rc_cgroup_mode="legacy"
   ```
   Verified active after reboot via `mount | grep cgroup` (classic multi-hierarchy v1 mounts) and the absence of `/sys/fs/cgroup/cgroup.controllers` (which would only exist under v2).
2. Use a **static, older `runc` binary (v1.1.12)** instead of whatever ships with the Docker package — renamed to `/usr/local/bin/runc-old` — and make it Docker's default runtime, with the cgroup driver set to plain `cgroupfs` (not systemd) since this is OpenRC, not systemd:
   ```json
   // /etc/docker/daemon.json
   {
     "exec-opts": ["native.cgroupdriver=cgroupfs"],
     "default-runtime": "runc-old",
     "runtimes": {
       "runc-old": { "path": "/usr/local/bin/runc-old" }
     }
   }
   ```

### Verification
```
docker rm -f nginx-bridge   # (only needed if a stale container from a previous attempt is in the way)
docker run -d --name nginx-bridge -p 8080:80 nginx:alpine
```
Confirmed: real Docker bridge networking (not host-mode) — container got IP `172.17.0.2/16` on the `docker0` bridge via a veth pair, port 8080→80 forwarded correctly, `curl` to the phone's port 8080 returned a genuine HTTP 200 from nginx.

---

## Phase 4 — Machine limits (for future planning, e.g. Home Assistant)

- **CPU:** Kirin 650 — 8× Cortex-A53 big.LITTLE, 4 cores @ ~2.11 GHz + 4 cores @ ~1.71 GHz.
- **RAM:** 1.7 GB total, ~1.5 GB typically available.
- **Swap:** none active by default (zram present but inactive, 0 B used).
- **Storage:** ~9.9 GB rootfs (≈8.3 GB free at time of check) plus a completely unused **10.6 GB `mmcblk0p49`** eMMC partition available for repurposing (this was the stock `/data` partition under Android — see `kernel.txt`'s partition table for the full map, `mmcblk0p49` = 11,155,456 blocks ≈ 10.6 GiB).
- Home Assistant Core was assessed as **feasible as a light hobby instance** if zram swap is enabled first. `cloudflared` for remote tunnel access was originally assessed as not feasible because the phone had no independent internet path. **That blocker is gone now that Wi-Fi works (Phase 5)**, so it's worth revisiting.

---

## Phase 5 — Wi-Fi bring-up (✅ working: IOT network, static IP 192.168.2.50, auto-connect at boot)

Wi-Fi works and comes up on its own at boot. This took several separate fixes, recorded below in the order they were found. The **"Current working setup"** subsection is the part to rebuild from; everything after it is history and dead ends, kept so nobody re-investigates them.

### Hardware/driver background (still accurate)
- `CONFIG_MODULES is not set`: there is no loadable-module support at all. Anything kernel-side has to be built in (`=y`) and reflashed.
- Chip: **HiSilicon Hi1102** WiFi/BT/GNSS combo on SDIO (device-tree `hi1102,*`, `/proc/device-tree/hisi_wifi/*`).
- The vendor kernel tree (`android_kernel_huawei_vns` @ `c93d7f0aedb5c5ea608a891a530979976d537998`) has the full Hi1102 driver as C source in `drivers/connectivity/hisi/{wifi,platform,common}/`. It is already enabled in `config-huawei-venus.aarch64` (`CONFIG_HI1102_WIFI=y`, `_HMAC`, `_WAL`, `_MAIN`, `CONFIG_HI1102_PLATFORM=y`, …). **No kernel changes were needed for Wi-Fi.** `CONFIG_HI1102_WIFI_DMAC` is off, and that's correct: DMAC runs as firmware on the chip, not in the host kernel.
- Layers: `wal` (cfg80211/nl80211 glue) → `hmac` (host MAC) → SDIO/HCC → `dmac` (firmware on the chip's own CPU).
- Bring-up is manual by design. Two sysfs triggers, both of which must receive the literal string `init`:
  ```
  echo init > /sys/hisys/boot/plat     # platform: SDIO, power, firmware download
  echo init > /sys/hisys/boot/wifi     # wifi host stack; creates wlan0, p2p0, Hisilicon0
  cat /sys/hisys/boot/plat /sys/hisys/boot/wifi   # "running" / "running" when up
  ```
- Interfaces the driver creates: `wlan0` (managed STA, MAC `14:11:02:fc:f1:54`), `p2p0` (the driver's own P2P-device), and `Hisilicon0`. `Hisilicon0` is an all-zero-MAC private/debug netdev used as the target for `hipriv` ioctls. It is **vap 0**, so `wlan0` is **vap 1**. That is normal for this driver.

### ⚠️ Rules for this driver (each one learned from a hang)
1. **Never** `echo deinit > /sys/hisys/boot/wifi`. It wedges the kernel (ping still answers, SSH dies) and needs a hard power-off.
2. **Never let anything create an extra P2P interface.** wpa_supplicant's default behaviour (`p2p-dev-wlan0`) corrupts the driver's interface list: `iw dev` prints `p2p0` endlessly, and the next shutdown hangs. That's why wpa_supplicant runs with `p2p_disabled=1`, and why NetworkManager must **not** manage `wlan0` (NM starts its own D-Bus wpa_supplicant, and that one creates the P2P interface).
3. If the phone gets into either state: hold Power about 10 s to force it off, then boot normally. Nothing on disk is affected.

### Current working setup (rebuild from this)

**1. Firmware: must match the host driver version.** Two firmware sets existed on the phone:

| File | Build string | Status |
|---|---|---|
| `/vendor/firmware/cr4_asic.bin` (original, from `shairhem/android_vendor_huawei_hi6250`) | `Hi1151 V100R001C01B371_20151022` | ❌ wrong version; backed up as `/vendor/firmware/cr4_asic.bin.C01B371-backup` |
| `/lib/firmware/postmarketos/cr4_asic.bin` (same blob as GitLab `ignapk/warsaw-firmware` @ `ce27f92d`) | `Hi1151 V100R001C02B201_20160607` | ✅ exact match for the host driver |

The host driver source pins the device version: `drivers/connectivity/hisi/wifi/dmac/dmac_config.c` → `"Hi1151 V100R001C02B201_20160607"`. Find the version of any blob with `strings -n 8 cr4_asic.bin | grep "Hi1151 V"`.

Fix applied: `cp /lib/firmware/postmarketos/cr4_asic.bin /vendor/firmware/cr4_asic.bin` (md5 `77463ea6b0d7738a310db6b3b66f0764`).
- The P9 Lite's own `/vendor/firmware/wifi_cfg` and `bfgx_and_wifi_cfg` were **kept**. The warsaw (P10 Lite) versions of those files add `@double ANT` register writes that are specific to that board. Only the binary was swapped.
- `CPU_RAM_SCHED.bin` / `CPU_RAM_WBS.bin` (BT/GNSS cores) are still the old C01 versions. They aren't used by Wi-Fi. If Bluetooth is ever needed, swap these to the matching versions from the same source.

**2. Android-style paths the driver hardcodes:**
```
mkdir /system && ln -s /vendor /system/vendor   # wifi_cfg loads /system/vendor/firmware/cr4_asic.bin
mkdir -p /data/misc/wifi                          # efuse cache: /data/misc/wifi/efuse
```
- Driver config INI: devicetree `hisi_cust_cfg/ini_file_name` = `/vendor/etc/cfg_venus_l21_hisi.ini` (present and loading; it contains `country_code=NO`).
- The boot-log warnings `hisi_customize_wifi read ini file failed, check if cfg_id[25/26/27/31/32/33] exists`, `read nvm failed` and `read dts instead` are **harmless**. Those IDs are CPU/DDR frequency-throttle levels, device-type tiers, the power-management switch, log level and a PHY register, not scan or country settings. The driver falls back to devicetree defaults.

**3. wpa_supplicant config:** `/etc/wpa_supplicant/wpa_supplicant.conf` (root, 600):
```
ctrl_interface=/run/wpa_supplicant
ctrl_interface_group=wheel
update_config=0
p2p_disabled=1          # <- critical, see rule 2
country=JO

network={
	ssid="IOT"
	psk="<IOT password — stored only in the file on the phone>"
	key_mgmt=WPA-PSK
}
```

**4. IP settings:** `/etc/conf.d/hisi-wifi`:
```
IP_MODE="static"              # or "dhcp"
IP_ADDR="192.168.2.50/24"
IP_GW="192.168.2.1"
IP_DNS="192.168.2.1 1.1.1.1"
WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
```
192.168.2.50 was confirmed unused by ARP before it was assigned. DHCP leases on this network had come back as .164 and .240, so .50 should sit outside the router's pool. **To be safe, also reserve or exclude .50 on the IOT router.**

**5. Boot service:** `/etc/init.d/hisi-wifi` (755), enabled with `rc-update add hisi-wifi default`:
```sh
#!/sbin/openrc-run
description="Bring up HiSilicon Hi1102 WiFi and connect via wpa_supplicant (P2P disabled)"

: ${IP_MODE:=dhcp}
: ${WPA_CONF:=/etc/wpa_supplicant/wpa_supplicant.conf}

depend() {
	need udev localmount
	after bootmisc
	before networkmanager
}

start() {
	ebegin "Initializing hisi wlan"
	[ "$(cat /sys/hisys/boot/plat)" = "running" ] || echo init > /sys/hisys/boot/plat
	[ "$(cat /sys/hisys/boot/wifi)" = "running" ] || echo init > /sys/hisys/boot/wifi
	i=0; while [ ! -e /sys/class/net/wlan0 ] && [ $i -lt 20 ]; do sleep 1; i=$((i+1)); done
	ip link set wlan0 up
	eend $? || return 1

	ebegin "Starting wpa_supplicant on wlan0"
	start-stop-daemon --start --exec /usr/sbin/wpa_supplicant -- \
		-B -D nl80211 -i wlan0 -c "$WPA_CONF" -P /run/wpa_supplicant.wlan0.pid
	eend $? || return 1

	if [ "$IP_MODE" = "static" ]; then
		ebegin "Configuring static IP ${IP_ADDR} on wlan0"
		ip -4 addr flush dev wlan0
		ip -4 addr add "$IP_ADDR" dev wlan0
		ip route replace default via "$IP_GW" dev wlan0
		{ for d in $IP_DNS; do echo "nameserver $d"; done; } > /etc/resolv.conf
		eend $?
	else
		ebegin "Starting DHCP on wlan0"
		udhcpc -i wlan0 -b -p /run/udhcpc.wlan0.pid >/dev/null 2>&1
		eend $?
	fi
}

stop() {
	# Never "echo deinit" to /sys/hisys/boot/wifi: it hangs this driver.
	ebegin "Stopping wlan0 clients"
	[ -f /run/udhcpc.wlan0.pid ] && kill "$(cat /run/udhcpc.wlan0.pid)" 2>/dev/null
	[ -f /run/wpa_supplicant.wlan0.pid ] && kill "$(cat /run/wpa_supplicant.wlan0.pid)" 2>/dev/null
	rm -f /run/udhcpc.wlan0.pid /run/wpa_supplicant.wlan0.pid
	ip -4 addr flush dev wlan0 2>/dev/null
	eend 0
}
```
The vendor package's own `hisi-wlan` service (pmaports `main/hisi-wlan`) is **not installed** on this phone. `hisi-wifi` replaces it.

**6. Keep NetworkManager off Wi-Fi:**
```
# /etc/NetworkManager/conf.d/99-unmanage-wlan0.conf
[keyfile]
unmanaged-devices=interface-name:wlan0

# /etc/NetworkManager/conf.d/90-hisi-wifi.conf
[main]
dns=none                        # NM must not overwrite /etc/resolv.conf (written by hisi-wifi)
[device]
wifi.scan-rand-mac-address=no
[connection]
wifi.cloned-mac-address=permanent
```
NetworkManager still runs and handles everything else.

### Verified after a cold reboot (2026-10-31 22:20)
```
rc-service hisi-wifi status     → started
/sys/hisys/boot/wifi            → running
wpa_cli -i wlan0 status         → ssid=IOT, bssid=e6:fa:c4:60:a8:1d, freq=2437 (ch 6), WPA2-PSK, COMPLETED
ip -4 addr show wlan0           → 192.168.2.50/24
ip route                        → default via 192.168.2.1 dev wlan0
/etc/resolv.conf                → 192.168.2.1, 1.1.1.1
ping 1.1.1.1                    → 0% loss, ~8 ms
nslookup google.com             → resolves
iw dev                          → 2 interfaces (wlan0, p2p0): clean, no P2P duplication
from the Deck: ping 192.168.2.50 and ssh user@192.168.2.50  → both OK
```

### Useful commands
```
sudo rc-service hisi-wifi restart            # safe: never touches deinit
sudo wpa_cli -i wlan0 status
sudo iw dev wlan0 scan | grep -E "SSID|signal"
dmesg | grep -E "wal_|hmac_|err_code"        # driver logs; err_code[2] = MAC_SCAN_TIMEOUT
```
To change networks, edit the `network={}` block in `wpa_supplicant.conf` and restart `hisi-wifi`. To go back to DHCP, set `IP_MODE="dhcp"`.

### How it was debugged (history)
1. **First trigger hung the system.** That was the original state of this phase. In a later session plat/wifi init turned out to be stable on its own. The hangs came from rules 1 and 2 above, not from bring-up.
2. **`filp_open [/system/vendor/firmware/cr4_asic.bin] fail`.** `wifi_cfg` uses Android paths. Fixed with the `/system/vendor` symlink. Firmware then downloaded and `wlan0` appeared.
3. **`store efuse into /data/misc/wifi/efuse fail` (errno -2).** Fixed with `mkdir -p /data/misc/wifi`. This was cosmetic; the efuse read itself had worked.
4. **NetworkManager scan → kernel wedge.** The workaround was to mark `wlan0` unmanaged. The real cause (rule 2) was found later.
5. **Scans returned 0 BSS every time**, even with many networks in range. dmesg showed:
   ```
   [vap:1] wal_cfg80211_scan::start a new normal scan. n_channels[13]
   [vap:0] hmac_scan_proc_scan_comp_event::Report vap(0) Scan_complete(cookie 0), but there have anoter vap(1) scaning(cookie 0) !
   ... 4.5 s later ...
   [vap:1] hmac_scan_proc_scan_timeout_fn::scan time out cookie [0].
   [vap:1] wal_scan_comp_proc_sta::scan not succ, err_code[2]!     # MAC_SCAN_TIMEOUT
   [vap:1] wal_inform_all_bss::there are 0 bss not in regdomain, so inform kernal bss num is [0]!
   ```
   The "complete" event arrives 3 ms after the scan starts, which is far too soon for a real 13-channel scan. The host discards it because the vap doesn't match, and the scan then times out. **Root cause: firmware/host version mismatch (C01 firmware on a C02 host driver)**, so the driver misreads the device's messages. Swapping `cr4_asic.bin` fixed it: the first scan afterwards returned 12 networks.
   - Dead ends ruled out on the way: regdomain filtering (that log line reports a truly empty total), `iw reg set JO` (no effect, irrelevant), the missing INI cfg_ids (unrelated settings), the "vap race needs a kernel patch" theory (wrong; it was the firmware), and deleting `p2p0` (`iw dev p2p0 del` returns EINVAL, and wasn't the cause anyway).
   - Also watch for `command failed: Network is down (-100)` from `iw scan`. It just means `wlan0` is administratively down: run `ip link set wlan0 up`.
6. **NetworkManager + D-Bus wpa_supplicant → `Couldn't initialize supplicant interface: Timeout`**, then an endless `p2p0` list and a shutdown hang. Root cause: wpa_supplicant creating `p2p-dev-wlan0`. Fixed by running wpa_supplicant directly with `p2p_disabled=1`, outside NetworkManager (the `hisi-wifi` service).

---

## Phase 6 — Root access recovery (lost `user` sudo password)

The `user` account's password was unknown, so `sudo` didn't work. Fixed by having the initramfs write a sudoers drop-in onto the real root filesystem at boot.

### Key discovery: patches to `init.sh` never run
On this pmOS build, both initramfs stages (`init` and `init_2nd.sh`, plus `init_functions*.sh`) are packed into the **same** ramdisk. Line ~45 of `init.sh` calls `jump_init_2nd`, which **`exec`s into `init_2nd.sh`**. Everything after that line in `init.sh` is dead code. Six patch attempts (v1–v6) inserted there were present in the packed ramdisk, as confirmed by unpacking it, but never ran. The decisive test was writing a marker file to the already-mounted `/boot`; it never appeared.

### Working patch (v7): `init_2nd.sh`
File (on the Deck): `~/.local/var/pmbootstrap/chroot_rootfs_huawei-venus/usr/share/initramfs/init_2nd.sh`. The original is saved alongside as `init_2nd.sh.orig-backup`. This block was inserted directly after `resize_filesystem_after_mount /sysroot` (that is, after the real `mount_root_partition`, with the rootfs mounted read-write at `/sysroot`):
```sh
# --- recovery patch v7: grant passwordless sudo to user ---
{
  echo "=== recovery patch v7 run ==="
  mkdir -p /sysroot/etc/sudoers.d
  cat > /sysroot/etc/sudoers.d/90-recovery << 'SUDOEOF'
# wifi-debug-recovery: added by initramfs one-time patch v7
user ALL=(ALL) NOPASSWD: ALL
SUDOEOF
  chmod 0440 /sysroot/etc/sudoers.d/90-recovery
  ls -la /sysroot/etc/sudoers.d/
  echo "=== end v7 ==="
} > /sysroot/recovery-patch-v7.log 2>&1
sync
# --- end recovery patch v7 ---
```
Build and flash:
```
pmbootstrap chroot -r -- mkinitfs        # repacks boot.img with correct headers via boot-deploy
fastboot flash boot <boot.img> && fastboot reboot
```
(`mkinitfs` reads the patched files straight from the chroot. Building boot.img by hand with `mkbootimg` isn't needed. This device's fastboot doesn't support RAM-only `fastboot boot`, so flashing is required.)

Verified: `/recovery-patch-v7.log` shows rc=0 for every step, `sudo -n true` succeeds, and `sudo whoami` prints `root`.

### Notes
- The flashed boot image **re-applies this on every boot**, and the patched `init_2nd.sh` is still in the chroot, so **any future `mkinitfs`/kernel build on the Deck will include it.** To remove it: restore `init_2nd.sh.orig-backup`, rebuild and flash, then delete `/etc/sudoers.d/90-recovery` on the phone.
- The sudoers file lives on the rootfs, so it survives even if the older `boot-known-good-pkgrel15.img` is flashed back.
- Optionally, set a real password now (`sudo passwd user`) so this isn't the only way in.
- TWRP/recovery-based alternatives weren't viable (no TWRP build for this device under pmOS), so they weren't pursued.

---

## Phase 7 — Home Assistant + nginx on Docker, swap, utilization (✅ 2026-10-31)

### zram swap (stock service is broken here)
`postmarketos-zram-swap` fails at boot for two reasons: it runs `modprobe zram` (this kernel has no module support, and zram is built in), and it picks `zstd`, which this kernel lacks (available: `lzo lz4 deflate`). It was removed from the runlevel (`rc-update del postmarketos-zram-swap default`) and replaced with `/etc/local.d/zram-swap.start` (runs through the `local` service):
```sh
#!/bin/sh
grep -q ^/dev/zram0 /proc/swaps && exit 0
echo 1 > /sys/block/zram0/reset 2>/dev/null
echo lz4 > /sys/block/zram0/comp_algorithm
echo 1G > /sys/block/zram0/disksize
mkswap /dev/zram0 >/dev/null
swapon -p 100 /dev/zram0
```
Plus `/etc/sysctl.d/90-zram.conf`: `vm.swappiness=100`.

### Containers (both `--restart unless-stopped`; the `docker` service is in runlevel `default`)
```
docker run -d --name nginx --restart unless-stopped -p 8080:80 --memory 64m \
  -v /srv/p9-web:/usr/share/nginx/html:ro \
  -v /srv/p9-nginx/default.conf:/etc/nginx/conf.d/default.conf:ro \
  nginx:alpine      # serves the status page (Phase 8); conf adds Cache-Control: no-cache

docker run -d --name homeassistant --restart unless-stopped --network host \
  -e TZ=Asia/Amman -v /srv/homeassistant:/config -v /etc/localtime:/etc/localtime:ro \
  ghcr.io/home-assistant/home-assistant:stable
```
- nginx: http://192.168.2.50:8080/ (bridge network, as in Phase 3).
- Home Assistant: http://192.168.2.50:8123/. Host network is used so device discovery (mDNS/SSDP) works. Config lives in `/srv/homeassistant`. It runs fine on this kernel through `runc-old` and cgroup v1 (Python 3.14 image, no errors). The image pull is about 1.5 GB and took about 2.5 minutes over Wi-Fi.
- **Onboarding is not done yet**: open :8123 to create the owner account.
- After a reboot: SSH is up, then nginx answers about 20 s later and Home Assistant about 30 s later. Both were verified from the LAN.
- Docker warns `kernel does not support swap limit capabilities`. That's expected (cgroup v1 without swap accounting); `--memory` limits still apply to RAM.

### Utilization (idle, measured 3 min after boot with both containers running)
| Metric | Value |
|---|---|
| CPU busy (60 s average, all 8 cores) | **0.2%** |
| Load average | ~10. **Ignore it**: about ten Huawei vendor kernel threads (`rdr_*`, `mailbox*`, `bbox_main`, `chr_*`) sit permanently in D-state and inflate it. Use CPU busy % instead. |
| RAM | 495 MB used / 1737 MB, **1247 MB available** |
| Home Assistant | 308 MB RSS, 38 PIDs |
| nginx | 6 MB (64 MB cap) |
| Swap (zram lz4) | 1 GB, 0 used |
| Disk `/` | 4.2 GB used / 9.9 GB, **5.1 GB free** (plus the unused 10.6 GB `mmcblk0p49`) |
| Temperatures | SoC 40 °C, clusters 39–40 °C, battery 31 °C |
| CPU frequency | governor `performance` (both clusters pinned at max: 1.71 / 2.11 GHz) |
| Battery | 100%, Full, on USB power |
| Wi-Fi link | RSSI −55 dBm, 135 Mbit/s |

Headroom: about 1.2 GB RAM and 5 GB disk, with the CPU nearly idle. Expect Home Assistant to grow (typically 400–600 MB) as integrations and history are added. Moving `/var/lib/docker` to `mmcblk0p49` is the obvious next step if disk gets tight.

---

## Phase 8 — LCD status dashboard + bash login shells (2026-10-31)

### How the display works (hisifb quirks)
- `/dev/fb0` = `hisifb0`, 1080×1920, 32 bpp, **BGRA** byte order (`rgba 8/16,8/8,8/0,8/24`), stride 4320, 3 buffers (virtual 1080×5760). The panel is a **BOE OTM1906C command-mode** LCD.
- Command mode: writing pixels does nothing visible until `FBIOPAN_DISPLAY` (ioctl `0x4606`) pushes a frame (watch `/sys/class/graphics/fb0/frame_count`).
- **The panel powers ON when `/dev/fb0` is opened and OFF (`hw_lcd_off`) when the last fd closes**, as on Android, where SurfaceFlinger holds it open. Anything that shows content must keep the fd open.
- ⚠️ **Never call `FBIOBLANK`** (ioctl `0x4611`). Unblanking on top of the open-triggered power-on crashed the phone, and the hardware watchdog rebooted it.
- If the panel is off, `FBIOPAN_DISPLAY` returns harmlessly (it logs `panel power off!`).
- Backlight: `/sys/class/leds/lcd_backlight0/brightness` (0–255, min usable about 3). There's no `/sys/class/backlight`.

### `p9-display` service
- Program: `/usr/local/bin/p9-display` (Python, standard library only, built-in 5×7 pixel font, 6× scaling, 1-pixel anti-burn-in shift every refresh).
- Service: `/etc/init.d/p9-display` (runlevel `default`, after `hisi-wifi` and `docker`), logging to `/var/log/p9-display.log`.
- Settings: `/etc/conf.d/p9-display` → `P9_BRIGHTNESS=60`, `P9_INTERVAL=10` (seconds).
- Shows: hostname, clock, date, uptime; Wi-Fi SSID, RSSI, Wi-Fi and USB IPs; CPU, RAM, swap, disk, SoC temperature; battery % with **CHARGING / FULL PLUGGED / ON BATTERY** and current in mA (from `/sys/class/power_supply/{Battery,USB,Mains}`); nginx and Home Assistant UP/DN (HTTP checks).
- Cost: about 0% CPU, about 17 MB RSS.
- `rc-service p9-display stop` blanks the screen and sets the backlight to 0.
- Replaced `/etc/local.d/disable-backlight.start`, now renamed `.disabled`.

### Status web page on nginx (http://192.168.2.50:8080/)
- `p9-display` also publishes every refresh into `/srv/p9-web/` (setting `P9_WEB_DIR`, default `/srv/p9-web`), using an atomic write-then-rename:
  - `status.json`: hostname, time, uptime, Wi-Fi (SSID, RSSI, state, IP), USB IP, CPU %, RAM, swap, disk, SoC temperature, battery (%, status, CHARGING/FULL PLUGGED/ON BATTERY, external power, current in mA, temperature), services UP/DOWN.
  - `screen.png`: the exact frame drawn on the LCD (180×320 indexed PNG, written with the standard library only).
- `/srv/p9-web/index.html` is a static page that fetches `status.json` and `screen.png` every 10 s. It has cards for resources, power, network and services (with links to :8080 and :8123), plus the live screen copy. It adapts to light/dark mode and phone or desktop width, and shows a red dot when data is older than 60 s.
- nginx mounts `/srv/p9-web` read-only (see the Phase 7 `docker run`). `index.html` is safe to edit, because the daemon only rewrites `status.json` and `screen.png`.
- Machine-readable: `curl http://192.168.2.50:8080/status.json`

### Login shells
- `root` and `user` both use `/bin/bash` (`usermod -s /bin/bash`; previously `/bin/sh` and `/bin/ash`).
- oh-my-bash is installed for both (`~/.oh-my-bash`, `/root/.oh-my-bash`, theme `font`), loaded by `.bash_profile` → `.bashrc` on interactive logins. Non-interactive SSH commands are unaffected (`p9-verify` still passes 24/24).

---

## Boot sequence & persistence (what starts automatically)

Everything below is enabled at boot and was verified after a cold reboot on 2026-10-31 22:42 (all 24 checks passed).

| Order | Runlevel | Service | What it does |
|---|---|---|---|
| 1 | `boot` | `unudhcpd.usb0` | USB RNDIS `172.16.42.1/16` (fallback access path) |
| 2 | `boot` | `sysctl` | applies `/etc/sysctl.d/90-zram.conf` → `vm.swappiness=100` |
| 3 | `default` | `cgroups` | cgroup v1 (`/etc/rc.conf` → `rc_cgroup_mode="legacy"`) |
| 4 | `default` | `hisi-wifi` | Hi1102 init → wpa_supplicant (P2P off) → static `192.168.2.50/24`, gw/DNS `192.168.2.1` (`/etc/conf.d/hisi-wifi`); runs `before networkmanager` |
| 5 | `default` | `networkmanager` | everything except `wlan0` (unmanaged, `dns=none`) |
| 6 | `default` | `sshd` | SSH on all interfaces |
| 7 | `default` | `docker` | daemon (`runc-old`, cgroupfs); brings back `nginx` + `homeassistant` (`--restart unless-stopped`) |
| 8 | `default` | `local` | runs `/etc/local.d/*.start`: `zram-swap.start` (1 GB lz4 swap) |
| 9 | `default` | `p9-display` | LCD status dashboard (Phase 8) |

Intentionally **not** enabled: `postmarketos-zram-swap` (broken on this kernel, replaced by `zram-swap.start`), the stock `wpa_supplicant` service and the D-Bus-activated one (they create a P2P iface that crashes the driver), `hisi-wlan` (not installed; replaced by `hisi-wifi`).

Approximate timings after power-on: SSH about 60 s; nginx +20 s; Home Assistant +30 s.

### Health check: `/usr/local/bin/p9-verify`
Run it on the phone (`ssh user@192.168.2.50 p9-verify`). It prints PASS/FAIL for: all six services; Wi-Fi association, static IP, route, DNS, internet, no stray DHCP client, a clean driver interface list; USB RNDIS; zram active, lz4, swappiness; cgroup v1; the `runc-old` runtime; both containers running and returning HTTP 200; and passwordless sudo. It ends with a memory, container, disk and temperature snapshot.

Last result (cold boot, uptime 1 min):
```
24/24 PASS
Mem: 491 MB used / 1737, 1250 MB available; swap 0/1024 MB
homeassistant 305 MB, nginx 6 MB; disk 4.2 GB used / 5.1 GB free; SoC 39 °C
From LAN: nginx :8080 → 200, HA :8123 → 200
```

---

## Reference: key files and locations

| What | Where |
|---|---|
| Bootloader unlock key (this device) | `NLYDI815YRQUUDUJ` |
| Unlock tooling | `~/p9lite-linux/PotatoNV-crossplatform/`, `~/p9lite-linux/potatonv-csharp/`, `~/p9lite-linux/runner/unlock_shim.py` |
| Stock Android reference dumps | `~/p9lite-linux/{android-properties,adb-devices,bootloader-info,fastboot-info,fastboot-vars,kernel.txt}` |
| pmbootstrap build env (on "the Deck") | `~/p9lite-linux-deck/pmb-venv/` (use the full path to `pmbootstrap`, not bare `pmbootstrap`, in non-login shells) |
| Kernel config actually used | `pmaports/device/testing/linux-huawei-venus/config-huawei-venus.aarch64` (on the Deck) |
| Kernel source tarball (cached) | `~/.local/var/pmbootstrap/cache_distfiles/linux-huawei-venus-c93d7f0a….tar.gz` (on the Deck) |
| Known-good boot image (rollback target) | `~/p9lite-backups/boot-known-good-pkgrel15.img` (sha256 `30d70138d54cfd169668fba24706bc78fee44da85aea2112a54f9687855d8e07`), pre-sudo-patch |
| initramfs sudo patch | `…/chroot_rootfs_huawei-venus/usr/share/initramfs/init_2nd.sh` (original: `init_2nd.sh.orig-backup`) on the Deck |
| Root on the phone | `/etc/sudoers.d/90-recovery` (`user ALL=(ALL) NOPASSWD: ALL`) |
| Docker config (on phone) | `/etc/docker/daemon.json`, `/usr/local/bin/runc-old` (static runc v1.1.12) |
| cgroup mode (on phone) | `/etc/rc.conf` → `rc_cgroup_mode="legacy"` |
| USB IP | `172.16.42.1/16` over USB RNDIS, via pmOS's built-in `unudhcpd` |
| Direct access | the Mac reaches `user@192.168.2.50` directly; the Deck hop is not required |
| **Wi-Fi IP** | **`192.168.2.50/24`** on SSID `IOT`, gateway/DNS `192.168.2.1`, MAC `14:11:02:fc:f1:54` → `ssh user@192.168.2.50` |
| Wi-Fi boot service | `/etc/init.d/hisi-wifi` + `/etc/conf.d/hisi-wifi` (runlevel `default`) |
| Wi-Fi credentials | `/etc/wpa_supplicant/wpa_supplicant.conf` (root 600, `p2p_disabled=1`) |
| NM Wi-Fi exclusions | `/etc/NetworkManager/conf.d/{99-unmanage-wlan0,90-hisi-wifi}.conf` |
| Wi-Fi firmware (active) | `/vendor/firmware/cr4_asic.bin` = C02B201_20160607 (md5 `77463ea6…`); old C01 at `cr4_asic.bin.C01B371-backup` |
| Wi-Fi firmware cfgs / INI | `/vendor/firmware/{wifi_cfg,bfgx_and_wifi_cfg,…}` (P9 Lite originals), `/vendor/etc/cfg_venus_l21_hisi.ini` |
| Android path shims | `/system/vendor → /vendor` symlink, `/data/misc/wifi/` |
| Containers | `nginx` (:8080, serves `/srv/p9-web` status page), `homeassistant` (:8123, host net, config `/srv/homeassistant`) |
| Health check | `/usr/local/bin/p9-verify` on the phone |
| LCD dashboard | `/usr/local/bin/p9-display`, `/etc/init.d/p9-display`, `/etc/conf.d/p9-display` |
| Login shells | `/bin/bash` for root + user, oh-my-bash in `~/.oh-my-bash` |
| Swap | `/etc/local.d/zram-swap.start` (1 GB zram lz4), `/etc/sysctl.d/90-zram.conf` |
| Wifi driver source | `drivers/connectivity/hisi/{wifi,platform,common}/` in `android_kernel_huawei_vns` @ `c93d7f0aedb5c5ea608a891a530979976d537998` |

---

## Known gaps in this record

The exact step-by-step `pmbootstrap init`/first-flash commands (the very first time Android was wiped and pmOS was flashed) were run in an earlier work session whose transcript is no longer available to reconstruct verbatim. Phase 2 above reflects the confirmed *end state* and the build/flash *mechanics* reused throughout the project, pieced together from recovered files and later session records, rather than a literal command-by-command replay of that first install. Everything from Phase 3 onward is a record of commands and configs actually run and verified in the sessions that produced this file.

Not yet done: Home Assistant onboarding (owner account), Bluetooth/GNSS (old C01 `CPU_RAM_*` blobs, untested), a DHCP reservation for .50 on the router, a real password for `user`, and verifying NetworkManager can manage `wlan0` at all (it would need its D-Bus wpa_supplicant to start with P2P disabled).

---

## Phase 9 — Cloudflare Mesh node, nftables kernel (r16), build/flash/rollback (2026-11-01)

Written by the second AI session. Phases 1–8 were written by the first session and are left unchanged.

### 9.1 Goal
Run a Cloudflare Mesh node (formerly WARP Connector) on the phone so the home LAN is reachable through Cloudflare Zero Trust. The router (TP-Link Archer AX23, OpenWrt 24.10.5, 1.4 MB free flash, MT7621/MIPS) cannot host it, so the phone does.

### 9.2 What exists in Cloudflare
- Mesh node `p9lite` exists in the first account (`95e728b4ec3446631f012e92af2e483c`). Two accounts share a name; the first one is used.
- Its token lives only on the phone: `/etc/p9-mesh.env` (root:root, 600), content `MESH_NODE_TOKEN=...`. State volume `/srv/p9-mesh` (700).
- Container `mesh` (image `cloudflare/mesh:latest-arm64`, needs NET_ADMIN, NET_RAW, `/dev/net/tun`). It is stopped with restart policy `no` until the new kernel is running.
- The temporary user token `tunnelAdmin` was deleted. The account-level "Create Additional Tokens" token was NOT deleted (the delete click was blocked); decide whether to remove it in the dashboard.
- Never paste tokens into chat. The token was moved clipboard → ssh → root-only file.

### 9.3 Root cause of "registers but never connects"
The client builds `table inet cloudflare-warp` with `nft`. Kernel 4.4.252 (r15) had `NF_TABLES` and IPv6 chains but no `NF_TABLES_INET` / `NF_TABLES_IPV4`, so every `ip`/`inet` table failed. Legacy iptables works, but Mesh does not use it.

### 9.4 Kernel r16 change
In `device/testing/linux-huawei-venus/config-huawei-venus.aarch64` set to `=y`: `NF_TABLES_INET`, `NF_TABLES_IPV4`, `NFT_CHAIN_ROUTE_IPV4`, `NFT_CHAIN_NAT_IPV4`, `NFT_REJECT`, `NFT_REJECT_INET`, `NFT_REJECT_IPV4`, `NFT_REJECT_IPV6`, `NFT_MASQ`, `NFT_MASQ_IPV4`, `NFT_MASQ_IPV6`, `NFT_REDIR`, `NFT_REDIR_IPV4`, `NFT_REDIR_IPV6`, `NFT_DUP_IPV4`, `NFT_DUP_IPV6`, `NFT_CT`, `NFT_META`, `NFT_COUNTER`, `NFT_LIMIT`, `NFT_LOG`, `NFT_EXTHDR`, `NFT_HASH`, `NFT_RBTREE`, `NFT_QUEUE`, `NFT_COMPAT`. `pkgrel` 15 → 16, config checksum refreshed. Everything is built in (no modules).

### 9.5 New package `p9lite-extras`
Everything the first AI configured by hand on the running phone (lost on any reinstall) is now an apk and a dependency of `device-huawei-venus` (pkgrel 3):
- OpenRC services `hisi-wifi` and `p9-display` (+ `/etc/conf.d`), enabled in runlevel default
- `/usr/local/bin/p9-display` (LCD dashboard / homescreen; `P9_BRIGHTNESS`, `P9_INTERVAL`) and `/usr/local/bin/p9-verify`
- zram swap (`local.d/zram-swap.start`) + swappiness sysctl
- NetworkManager conf ignoring `wlan0`
- nginx status page/config under `/srv/p9-web`, `/srv/p9-nginx`

Deliberately not included: `wpa_supplicant.conf` (Wi-Fi PSK), `runc-old` (10 MB binary, kept in this repo), `passwd`, `fstab`, sudoers.

Screen shutdown: hisifb powers the panel off when `/dev/fb0` is closed, so `p9-display` holds it open. To turn the screen off, stop the service or `echo 0 > /sys/class/leds/lcd_backlight0/brightness`. `disable-backlight.start.disabled` is intentionally disabled.

### 9.6 Build procedure (Steam Deck, 8 cores, ~10 min for the kernel)
```
cd /home/deck/p9lite-linux-deck
PB="python3 pmbootstrap/pmbootstrap.py --details-to-stdout"
$PB checksum linux-huawei-venus p9lite-extras device-huawei-venus
$PB build linux-huawei-venus --arch aarch64 --force
$PB build p9lite-extras --arch aarch64 --force
$PB build device-huawei-venus --arch aarch64 --force
```
Helper script: `/home/deck/run-r16.sh` (log `/home/deck/p9lite-build-r16.log`, ends with `ALL_BUILT_OK`).

**Do not run any other pmbootstrap command (especially `checksum`) while a build is running.** It wipes the shared source tree and the kernel build dies with `generated/autoconf.h: No such file`. This happened once.

Inherited pitfalls: bare `Image` only (bootloader cannot decompress gzip; never build `Image.gz-dtb`); `downstreamkernel_prepare.sh` runs `oldconfig` with `yes ""`, so new options default silently — verify the final `.config`.

### 9.7 Git layout
- Mac `~/p9lite-linux`, branch `main`: docs, captured phone files, overlay copy of pmaports changes, unlock shim.
- Deck `~/p9lite-linux-deck/pmaports`: branch `p9lite/baseline-2026-11-01`, tag `p9lite-known-good-r15` (what was running), working branch `p9lite/nft-inet` (r16 + extras).

### 9.8 Flash and rollback
Known-good image: Deck `~/p9lite-backups/boot-known-good-pkgrel15.img`. Copy it to the Mac before flashing anything. Flash only with the phone in fastboot and the user's approval.

### 9.9 After the new kernel boots
1. `uname -a` shows build `#17` or later; `sudo nft add table inet t` succeeds.
2. `sudo docker start mesh`, then `sudo docker update --restart unless-stopped mesh`; `docker exec mesh warp-cli status` says Connected; node online in the dashboard.
3. Router: static route `100.96.0.0/12` via `192.168.2.50` (the phone is on the IOT VLAN) plus firewall rules between IOT and LAN. SRCNAT is currently disabled.

### 9.10 Findings kept for later
- Ethernet + charging: the hi6522 charger and OTG boost appear mutually exclusive, so a micro-USB OTG Ethernet adapter cannot also charge. Reliable options: a battery-side TP4056 charging module (soldering, risk) or stay on Wi-Fi.
- Home Assistant container is running (net=host) but unconfigured; no old backups exist, starting fresh.
- The router has no DHCP reservation for 192.168.2.50 (static IP on the phone).

### 9.11 Result of the r16 test (2026-11-01 16:05) — Mesh still cannot run on kernel 4.4
- r16 was built, flashed from the Deck (`pmbootstrap flasher flash_kernel`; image `deck:~/p9lite-backups/boot-r16-nft.img`, rollback `boot-known-good-pkgrel15.img`) and booted fine: `uname` shows `#17`, `nft add table inet` works, p9-display/hisi-wifi/docker/HA/nginx all started.
- Boot-image recipe used: `pmbootstrap index`; `pmbootstrap chroot -r -- apk add -u linux-huawei-venus device-huawei-venus p9lite-extras`; `pmbootstrap initfs build` (writes `chroot_rootfs_huawei-venus/boot/boot.img`); `pmbootstrap flasher flash_kernel`; `fastboot reboot`. The phone's USB goes to the Deck, not the Mac.
- The Mesh client's firewall script still fails: `table inet cloudflare-warp` → "Could not process rule: No such file or directory", and WARP stays Disconnected.
- Feature probe on the phone (4.4.252): works = inet filter chains, ct, sets/intervals, skuid, reject, ct mark. FAILS = `type route` chain in family inet, `type nat`/masquerade in family inet, `fib` expression in inet, `meta cgroup`. These are not config options: 4.4 has route/NAT chains only for ip/ip6 and no inet NAT/fib. Fixing it means backporting nf_tables inet route/nat/fib code from 5.x to 4.4, which is not worthwhile.
- Conclusion: the Mesh node must run on a host with a modern kernel (e.g. a Proxmox LXC/VM). The phone keeps HA, nginx and the dashboard. Container `mesh` is stopped, restart=no. The r16 kernel is harmless to keep.

---

## Phase 10 — Can the phone run the latest kernel (7.3.1)? Feasibility test (2026-11-01)

Question tested: "move Huawei's hardware drivers to the newest kernel as they are". Latest stable on kernel.org on test day: **7.3.1** (2026-10-30). Work dir on the Deck: `~/k7/` (`linux-7.3.1/`, `linux-4.4.252/` upstream, `vendor/` = the Huawei 4.4.252 tree, `port/` = compile-test logs, `shim/`, `ct.sh`, `inv.py`, `fdt.dts` = the phone's live device tree).

### 10.1 What the running phone actually uses
Read from the live phone (`/sys/bus/*/devices/*/driver` + `of_node/compatible`, 101 bound devices) and matched against driver compatible strings in 7.3.1:
- **Already in mainline:** CPU PMU, PL011 UART, pinctrl-single, eMMC card layer, ramoops, and the ARM AMBA blocks (PL061 GPIO, SP805 watchdog, PL022 SPI). GIC (`arm,cortex-a9-gic`), arch timer and PSCI are standard too.
- **Huawei/HiSilicon only (no 7.3.1 driver):** eMMC/SDIO host (`hisilicon,hi6250-dw-mshc`, close to mainline `dw_mmc-k3`), clocks (no hi6250 clock driver upstream; mainline has hi6220/hi3660/hi3670 only), reset, PMIC (`hisilicon,hisi-pmic`) + all regulators, RTC, power key, Wi-Fi/BT/GPS (Hi1102 `hisilicon,hi1102`, `hisi_wifi`, `oal_sdio`), USB OTG (`hi6250-usb-otg` + vendor dwc_otg), USB switch FSA9685, charger hi6522, fuel gauge (coul), thermal sensor (`hisi,tsens`), cpufreq/devfreq, display (hisifb + DSI panel), audio, sensors.
- Upstream `arch/arm64/boot/dts/hisilicon/` has no hi6250 device tree.
- 444 kernel options enabled on the phone do not exist in 7.3.1.

### 10.2 Compile test: vendor drivers built unmodified against 7.3.1
Harness `~/k7/ct.sh` (inside the pmbootstrap native chroot, `aarch64-alpine-linux-musl-gcc` 15.2): each driver copied out of the vendor tree and built as an external module against a 7.3.1 `defconfig`, with the vendor's own private headers on the include path and vendor-only CONFIG symbols defined.

| Driver (server-critical) | Source files | Compiled clean |
|---|---|---|
| eMMC/SDIO host `dw_mmc_hi3xxx.c` | 1 | 0 |
| PMIC + regulators + RTC | 3 | 0 |
| Thermal `hisi_tsens.c` | 1 | 0 |
| Charger `hisi_scharger_v200.c` (hi6522) | 1 | 0 |
| USB OTG `drivers/usb/susb` | 27 | 4 |
| Wi-Fi Hi1102 `drivers/connectivity` | 199 | 25 |

Typical errors are API changes, not trivia: `struct timeval`/`do_gettimeofday` removed; `regulator_register()` signature changed; thermal framework redesigned (`get_mode`, `get_trip_type`, `get_trip_temp` gone); wakelock and legacy GPIO (`gpio_request_one`, `GPIOF_*`) APIs removed; `kernel_read()` signature changed; `irq_domain_add_simple` renamed; `platform_driver.remove` / `i2c_driver.probe/remove` signatures changed; `del_timer`, `mmiowb` removed; `asm/unaligned.h` moved.

**Key finding:** the drivers are not self-contained. The Wi-Fi and eMMC host code depends on Huawei changes inside the kernel core (e.g. `MMC_CAP2_SUPPORT_WIFI`, `mmc_host->sdio_present` in the MMC core).

### 10.3 How much of the core kernel Huawei changed
`diff` of the vendor tree vs upstream 4.4.252 (files changed / lines changed; part of this is Android-common code, not Huawei):
kernel 156/28k, mm 75/9k, fs 314/66k, net 279/20k, block 32/14k, drivers/mmc/core 32/4.9k, drivers/base 35/4.2k, drivers/clk 269/39k, drivers/regulator 62/41k, drivers/power 85/61k, drivers/thermal 54/9k, drivers/cpufreq 50/8k, drivers/usb/dwc3 23/5.5k, arch/arm64 681/111k, include/linux 543/51k.

### 10.4 Build host benchmark: Steam Deck vs Mac (same 7.3.1 config, GCC 15.2)
- Steam Deck (Zen 2 4c/8t, cross-compiling x86→arm64 in the pmbootstrap chroot, Steam running): **31 min 43 s**.
- Mac M1 Pro via Podman (`podman machine` applehv, 8 vCPU / 9 GB, privileged `alpine:edge` container `p9build`, volume `p9work`, native arm64): **8 min 30 s**. Identical Image size (36,850,176 bytes).
- Decision: build on the Mac from now on; flash from whichever machine the phone's USB is plugged into (the Deck today). Mac has 51 GB free disk — keep build trees in the VM volume, not on a shared Mac folder.

### 10.5 Boot-test method and what the bootloader allows
- The Huawei bootloader takes the device tree from its own partition, not from boot.img (`deviceinfo_dtb=""`), so a mainline kernel receives the vendor DT. Its CPU (PSCI `smc`), GIC (`arm,cortex-a9-gic` @ 0xe82b1000), arch timer (1.92 MHz), memory and `ramoops` (reserved `pstore-mem` @ 0x34800000, 1 MiB) nodes are standard and usable by 7.x.
- `fastboot boot <img>` (RAM boot) is **not supported** by this fastboot ("invalid command"). Tests must be flashed.
- Partitions: `boot` = mmcblk0p28, 32 MiB; `recovery` = p29, 64 MiB; `recovery2` = p22, 64 MiB.
- **Boot-fail mode (learned the hard way 2026-11-06):** an AP watchdog reset (e.g. `p9test stop_feed`) makes the
  bootloader record a boot failure on the eMMC and boot `recovery2` (eRecovery) instead of `boot` on every power-on
  until stock eRecovery clears it via its **Reboot** menu entry. Button resets and full charge do not clear it.
  Symptom: whatever is in `boot` seems to "not start" (the screen stays on the unlocked-bootloader warning). Never
  put a custom image in `recovery2` (a boot image that works from `boot` hangs there) and never use a watchdog
  starve to escape a hung test kernel. Stock `recovery2` is `partitions/22-recovery2.img.gz` in the 2026-11-06 backup.
- Kernel load address is 0x480000 (base 0x478000 + 0x8000), which is not 2 MiB aligned. Kernels ≥5.8 have text_offset 0 and need 2 MiB alignment, so `~/k7/mkstub.py` prepends a 1.5 MiB stub (valid arm64 header, `b #0x180000`) placing the real Image at 0x600000.
- Rebooting into fastboot from Linux works with `reboot(…, LINUX_REBOOT_CMD_RESTART2, "bootloader")` (python ctypes one-liner).
- Trimmed test kernel: `allnoconfig` + fragment `p9min.config` (Mac container `/work/p9min.config`) → 6.4 MB Image, 80 s build. Note: `PSTORE` only sticks with `CONFIG_MISC_FILESYSTEMS=y`.
- Side note: postmarketOS package mirrors now redirect to `mirror.nura.eco` — this is where the "Nura" naming seen on the phone comes from.

### 10.6 Backups taken before flashing the test kernel (Mac `~/p9lite-backups/2026-11-01-pre-k7/`)
- `boot-p28.img` (raw 32 MiB; first 32,284,672 bytes identical to `deck:~/p9lite-backups/boot-r16-nft.img`), `recovery-p29.img` (raw 64 MiB), `phone-state.txt` (docker inspect, runlevels, cmdline, apk list), `rootfs-full.tar` (GNU tar, numeric owners, xattrs, ACLs, `/` + `/boot`, taken with Docker stopped).
- Restore boot: `fastboot flash boot boot-p28.img` (or the r16 image). Restore rootfs: boot r16, then untar over `/` from a USB-net/ssh stream.

### 10.7 Boot test result: Linux 7.3.1 boots on the P9 Lite (2026-11-01 17:43)
Full log: `k7/k7-boot-console-2026-11-01.txt` (409 lines, read from `/sys/fs/pstore/console-ramoops-0` under r16).
- **Works on stock mainline 7.3.1, no Huawei code:** all 8 Cortex-A53 cores (both clusters via PSCI v0.1 `smc`), GIC, arch timer (1.92 MHz) + SP804, 1.75 GB usable RAM, all vendor reserved-memory regions honoured, 4 pinctrl-single controllers, 31 PL061 GPIO controllers, 2 PL011 UARTs, initramfs unpacked, **userspace `/init` ran**, stable for 21 s, clean restart into fastboot.
- **Not working yet (expected):** no clock driver (hi6250 has none upstream), so eMMC (`hisilicon,hi6250-dw-mshc`), SDIO/Wi-Fi, USB, PMIC/regulators, thermal, display stay unbound. Mainline `dw_mmc-k3` was built in but does not match the hi6250 compatible.
- First attempt (no helper) crash-looped into **eRecovery**: the bootloader starts the SP805 watchdog (60 s) and Huawei's boot-fail monitor (`hw_bfm_enable=1`) gives up after a few failed boots.

### 10.8 Test harness that made it work (`k7/` in this repo; sources also in the Mac container `/work`)
- `p9test.c` — built-in helper (`drivers/misc`, `obj-y += p9test.o`): feeds the SP805 watchdog @0xE8A06000 every second; on any restart/panic writes reboot reason BOOTLOADER (0x01) into the PMIC reset register 0xFFF3462C (PMU SSI0 0xFFF34000 + 0x18B<<2, low byte) and pulses bit 2 of 0xFFF0A510 (NMI to LPM3), so the board stops in fastboot with RAM intact; copies the kernel log into the vendor ramoops console zone (0x34860000, 512 KiB, header `DBGC`/start/size) so r16 shows it as `console-ramoops-0`; prints a report of bound devices after `p9test.reboot_delay` s (default 20) and reboots to fastboot.
- Mainline ramoops cannot use the vendor DT node as-is: sizes are two-cell (64-bit) and mainline reads u32 → 0. `p9test` rewrites them, but the direct console-zone write is what is used (mainline `PSTORE` is disabled in the test config).
- `p9init.c` (static `/init`), `mkcpio.py` (initramfs), `mkstub.py` (2 MiB alignment stub), `p9min.config` (allnoconfig fragment), `mkboot7t.sh` (mkbootimg with the vendor offsets and cmdline `panic=1 rdinit=/init p9test.reboot_delay=20`).
- Test cycle (≈3 min, no buttons): r16 → `reboot(RESTART2,"bootloader")` → `fastboot flash boot boot-7.3.1-t.img` → `fastboot reboot` → phone returns to fastboot by itself after ~38 s → `fastboot flash boot boot-r16-nft.img` → reboot → read `/sys/fs/pstore/console-ramoops-0`.

### 10.9 Where this leaves the "latest kernel" path
Booting is solved; the work is now driver bring-up, in this order (each step testable with the cycle above):
1. **hi6250 clock driver** (new `clk-hi6250.c`, modelled on mainline hi6220/hi3660 + vendor clock tables) — everything else depends on it. Shortcut to try first: the bootloader already clocks and powers the eMMC, so a hi6250 entry in `dw_mmc-k3` with fixed/dummy clocks may give eMMC access before a real clock driver exists.
2. **eMMC** → boot the real rootfs on 7.3.1.
3. **USB device mode** (Synopsys dwc2 + hi6250 PHY glue) → ssh over USB, no more blind tests.
4. **PMIC + regulators**, power key, RTC, thermal (`hisi,tsens`), cpufreq.
5. **Wi-Fi (Hi1102 over SDIO)** — largest piece (~450k vendor lines, depends on vendor MMC core changes); port or rewrite as a cfg80211 driver.
6. Charger (hi6522) and fuel gauge — needed for safe 24/7 operation on battery.


---

## Phase 11 — Mainline 7.3.1 bring-up, Mac build pipeline, Hi1102 Wi-Fi port (ON HOLD, 2026-11-01)

Status: **on hold** at the user's request (credits). The phone is back on r16 (4.4.252, kernel #17) and is in production: Wi-Fi 192.168.2.50, Home Assistant, nginx.

### 11.1 Build host moved to the Mac
- Podman machine (applehv, 8 CPU / 9 GB), privileged container `p9build` (alpine:edge, gcc 15.2), volume `p9work` mounted at `/work`.
- Full kernel build: Mac 8m30s vs Deck 31m43s (about 3.7x faster). The Deck is retired as the build host.
- `/work` layout: `linux-7.3.1` (patched), `out7min` (trimmed boot build), `out7mod` (module build), `vendor/` (Huawei 4.4 tree), `busybox-1.37.0` (static, SHA HWACCEL off), `rootfs-usb/`, `p9-initrd.gz`, `hi1102/` (git), `compat/`, `shim/`.
- **Always build with `tools/kbuild.sh`.** It fails on any make error. A hidden modpost "Section mismatch" error once left a stale Image in place and cost about an hour of false "hangs".

### 11.2 Flashing from the Mac
- Homebrew fastboot 37 hangs the Huawei bootloader (getvar max-download-size / is-logical). Use `tools/p9fastboot.py` (pyusb, 18d1:d00d). A USB reset via `dev.reset()` unwedges the bootloader.
- `fastboot boot` is unsupported, so every test flashes the boot partition (32 MiB limit, hence the trimmed config `k7/p9min.config`).
- Restore r16: `tools/p9restore.sh` flashes `~/p9lite-backups/boot-r16-nft.img` (sha fd8665f2…). The fastboot reboot reason is sticky, so the script reboots twice.
- Full pre-k7 backup: `~/p9lite-backups/2026-11-01-pre-k7/` (boot, recovery, rootfs tar 4.79 GB, SHA256SUMS).

### 11.3 Booting 7.3.1 at all
- The bootloader supplies the DT; no DTB goes in boot.img. The kernel is loaded at 0x480000, so `k7/mkstub.py` prepends 0x180000 bytes plus a `b #0x180000` branch.
- mkbootimg: base 0x478000, kernel 0x8000, ramdisk 0x7b88000, second 0xe88000, tags 0x7588000, pagesize 2048.
- `k7/p9test.c` (built in as `drivers/misc`) provides:
  - Feeds and self-arms the SP805 watchdog at 0xE8A06000 (20 s).
  - Reboot to fastboot: PMU 0xFFF3462C = 0x01, then pulse bit 2 of the LPM3 NMI register 0xFFF0A510.
  - Writes the kernel log into the vendor ramoops console zone at 0x34860000, so r16 shows it as `/sys/fs/pstore/console-ramoops-0`.
  - Debugfs `p9test/sdio` trigger and module params.
  - The result: a failed boot always comes back to fastboot by itself, with a log.

### 11.4 What works on 7.3.1
| Part | State | How |
|---|---|---|
| CPU/RAM/IRQ/timers | ✅ | |
| eMMC | ✅ HS200, ~119 MB/s | Arasan 0xFF390000 → `arasan,sdhci-8.9a`, fixed clocks 200/120 MHz, CRG gates 0xFFF35040 b15 / 0xFFF35000 b13 |
| USB gadget | ✅ CDC-ECM to the Mac | Vendor PHY replay (PCTRL+0x64, ABB gate 0xFFF3443C b0, RSTDIS4 bits, AHBIF eye 0x06ac66db), dwc2 hi6220 peripheral, explicit FIFOs. Phone 172.16.42.1, shell `nc 172.16.42.1 2323`, `reboot -f` returns to fastboot |
| Root filesystem | ✅ read-only | loop -P on mmcblk0p49 → loop0p2 |
| Hi1102 SDIO | ✅ enumerates (0296:5347) | dwmmc2 0xFF37D000 as `hisilicon,hi3660-dw-mshc`, 3.2 MHz mux path, reset RSTDIS4 b19, **32 kHz clock = PMIC 0x121 bit 1 (not bit 0)**, power sequence 32k → pinctrl idle → gpio35 low → gpio91 high → gpio35 high → 200 ms → pinctrl default |
| Real clock driver (PLL AP branch) | ❌ | needed for full-speed SDIO |
| Wi-Fi driver | ❌ 115/199 files compile | see 11.5 |
| PMIC / thermal / cpufreq / charger / display | ❌ | not started |

### 11.5 Hi1102 Wi-Fi driver port (where it stopped)
- Source: Huawei vendor tree, imported into `/work/hi1102` git (base `fbde3bc`, last `fdd39a1`). Clean diff exported as `k7/hi1102-port/hi1102-7x.patch`.
- Build: `podman exec p9build sh /work/wifi-inventory.sh` (out-of-tree against `out7mod`, force-includes `k7/hi1102-port/p9_compat.h`, ccflags-y instead of EXTRA_CFLAGS).
- Done: OAL timers (timer_setup wrapper), time, wait queues, netdev, kernel_read, set_fs stubs, and band/rate renames.
- **Remaining (97 errors):**
  1. cfg80211 ops table in `wal_linux_cfg80211.c` (~26 errors). The exact 7.3.1 prototypes were extracted (`k7/hi1102-port/newsigs.py` prints them). Plan: thin adapter functions with the new signatures (wdev instead of netdev, link_id, radio_idx, `cfg80211_ap_update`, `u64 cookie` by value, `vif_params->flags`) calling the existing Huawei functions. Drop `mgmt_frame_register` and `wireless_handlers`. Use `max_sched_scan_reqs=1` and `wdev->u.ap.preset_chandef`.
  2. `oal_cfg80211.c` notifications: `cfg80211_scan_info`, `cfg80211_roam_info`, `sched_scan_results(wiphy,0)`, new_sta/del_sta on wdev.
  3. Per-file API drift: timers with `.data`/init_timer (plat_pm, green_ap, bfgx_exception_rst), old kernel_read (hisi_ini, plat_firmware), platform remove returning void, proc_ops, pm_qos, FB_EVENT_BLANK, ndo_select_queue, mmc_power_save/restore_host, wakelock ws pointer, atomic→refcount.
  4. Try to exclude bfgx/uart (BT/GNSS) from the Wi-Fi build.
  5. Link, load with firmware from `/vendor/firmware`, test association.
- Estimate to resume: several hours to compile, plus on-phone debugging.

### 11.6 Lessons
- Verify the image is fresh after every build (kbuild.sh); grep case-insensitively for ERROR.
- Write bit-level changes with read-modify-write. A blind write to the PMIC register cleared the 32 kHz clock and caused long SDIO OCR=0 confusion.
- Self-arm the watchdog in a test kernel. Never trust the bootloader to have done it.
- Write helper scripts to files and copy them in. Don't nest heredocs through ssh/podman.

### 11.7 Next step chosen: backport to the running 4.4 kernel (not started)
The reason for chasing 7.x was Cloudflare Mesh. It needs nftables `inet` route/nat/fib (`table inet cloudflare-warp`), which 4.4.252 lacks even in r16. Candidate backports into the 4.4 vendor tree:
- `nft_fib` (mainline 4.10)
- inet-family NAT chains (mainline 5.2, depends on the nf_nat core rework)
- Whatever else the warp client's ruleset uses. First capture the exact failing `nft` commands on the phone.
Expected effort: `nft_fib` is a small, self-contained module and is realistic. Inet NAT depends on the 4.18–5.2 netfilter NAT refactor and is large.
Cheaper alternatives:
- Run the Mesh node on another always-on host (e.g. a Proxmox LXC).
- Use a userspace WireGuard-based connector that only needs iptables.
