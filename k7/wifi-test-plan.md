# Hi1102 Wi-Fi on 7.3.1 — hardware test plan (image 7)

## What is being tested
Image 7 = image 6's driver (round 8: regdomain apply moved to a worker, fixes the rtnl self-deadlock on
`ip link set wlan0 up`) + a kernel whose p9test has a safe escape (`restart_now`) and no `stop_feed`.
Last hardware state (image 5): firmware runs, RF calibration done, wlan0 exists, `ip link up` deadlocked.

## Known traps and how each is handled
| Trap | Handling |
|------|----------|
| Watchdog reset -> Huawei boot-fail mode (bootloader boots recovery2 until eRecovery "Reboot") | `stop_feed` removed; escape only via `restart_now` (emergency_restart -> PMIC reason BOOTLOADER + LPM3 reset, the path every good test used) |
| `reboot`/`kernel_restart` hangs in device_shutdown behind a stuck driver | `restart_now` and the 30-min `reboot_delay` net both use emergency_restart (no device_shutdown) |
| Driver drops rtnl + `register_netdev` inside add_virtual_intf (7.x holds wiphy lock there) | not on the path: no P2P/AP interfaces; phone's wpa_supplicant.conf has `p2p_disabled=1` |
| nc shell on :2323 blocks on a hung command | every step runs over telnet :23 (one shell per connection) with a time limit |

## Steps (each has a pass condition and a stop condition)
0. Preconditions: r16 healthy, recovery2 = stock (sha 679fa467…), battery full.
1. Escape check: flash image 7, boot, `echo 1 > /sys/module/p9test/parameters/restart_now`.
   Pass: fastboot within 30 s. Fail: stop, restore r16 (do not test Wi-Fi without a working escape).
2. Boot image 7 again. `p9wifi mount`, `sdio`, `load`, `init` one at a time (60 s limit each).
   Pass: plat/wifi `running`, wlan0 UP. Hang: save dmesg + stacks of D-state tasks, then step 5.
3. `p9wifi scan`. Pass: BSS list containing "IOT".
4. `p9wifi connect` (r16 is off the LAN, so .50 is free). Pass: ping 192.168.2.50 from the Mac.
5. Always: save dmesg to k7/logs, `restart_now` -> fastboot -> `tools/p9restore.sh` -> verify HA/nginx/Wi-Fi.

## Result (2026-11-06 21:33–21:43, `boot-test-wifi7.img`, sha 271e2210…)
- Step 1 PASS: `restart_now` -> fastboot in 6 s.
- Step 2 PASS: Hi1102 enumerated, plat/wifi running, `ip link set wlan0 up` rc=0 (round 8 fixed the deadlock).
- Step 3 PASS: 7 BSS, "IOT" at -58 dBm.
- Step 4 PASS: WPA2-PSK COMPLETED on IOT (2437 MHz), 192.168.2.50, Mac ping 60/60, avg 29 ms.
- Step 5 PASS: restart_now -> r16 restored; HA 200, nginx 200, boot/recovery2 sha match.
- Logs: `logs/*-wifi7-wlan0-up.txt`, `*-wifi7-connected.txt`, `*-wifi7-connected-pstore.txt`.

## Open (next round)
- `dev_addr_check` WARN: driver writes `netdev->dev_addr` directly -> use `eth_hw_addr_set()`.
- MAC is random (84:11:02:…) because `hisi_nve_direct_access` is stubbed; real MAC f0:11:02:xx:xx:xx lives in
  NVE item 193 (nvme partition) -> read it from the nvme partition or pass via module param.
- ini values missing (cfg_id 79-86, sdio_assem, loglevel, chn_est_ctrl): defaults used; check perf.
- P2P/AP: driver drops rtnl + `register_netdev` inside add_virtual_intf -> deadlocks under 7.x wiphy lock.
- Latency spikes (max 172 ms): likely power save; check `iw dev wlan0 set power_save off`.
- Test helper: run long steps detached (`setsid … &`) over telnet; one command per line.
