#!/usr/bin/env python3
"""P9 lite, mainline: supervised one-time discharge to the 80% charge limit.
Method: pause p9-charger and set the hi6522 input current limit to its minimum (100 mA, BUCK_REG4 bits 4-7
= 0); the phone draws more than that, so the battery supplies the rest (~150 mA). Restoring = restarting
p9-charger, which re-applies the 1 A limit. (The vendor Hi-Z GPIO, PL061 @0xE8A10000 pin 7, does not cut
the input on this board - tried, battery current stayed ~0.) Fuel gauge sign: positive = discharging.
  p9-discharge.py [TARGET_MV=4100] [MAX_HOURS=6]       (4.10 V loaded ~ 4.13 V at rest = 80%)
  p9-discharge.py --restore                            reconnect the input now
Safety: input is restored on reaching TARGET, below 3.90 V, after MAX_HOURS, on any read error, on
SIGTERM/SIGINT, and by an independent dead-man process (MAX_HOURS + 15 min) if this one dies. A reboot
also resets the pin (input pulled low = input on). Log: stdout."""
import mmap, os, signal, struct, subprocess, sys, time
GPIO, BIT = 0xE8A10000, 7
fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
g = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=GPIO)
rd = lambda o: struct.unpack_from("<I", g, o)[0]
wr = lambda o, v: struct.pack_into("<I", g, o, v)
DATA = (1 << BIT) << 2                              # PL061 masked data address for this pin

def hiz(on):
    """on: input limited to 100 mA (battery supplies the rest); off: p9-charger restores everything."""
    if on:
        subprocess.run(["rc-service", "p9-charger", "stop"], capture_output=True)
        cur = int(subprocess.run(["i2cget", "-f", "-y", "0", "0x6b", "0x3a"], capture_output=True, text=True).stdout, 16)
        subprocess.run(["i2cset", "-f", "-y", "0", "0x6b", "0x3a", hex(cur & 0x0F)], check=True)
    else:
        wr(DATA, 0); wr(0x400, rd(0x400) & ~(1 << BIT))           # make sure the Hi-Z GPIO is off too
        subprocess.run(["rc-service", "p9-charger", "start"], capture_output=True)
        subprocess.run(["python3", "/usr/local/bin/p9-charger", "--once"], capture_output=True)

def bat():
    uv, ua = (int(x) for x in open("/sys/module/p9test/parameters/battery").read().split()[:2])
    return uv // 1000, ua // 1000

def log(msg):
    print("%s %s" % (time.strftime("%F %T"), msg), flush=True)

if "--restore" in sys.argv:
    hiz(False); log("input restored (pin %d input, level 0)" % BIT); sys.exit(0)

target = int(sys.argv[1]) if len(sys.argv) > 1 else 4100
max_h = float(sys.argv[2]) if len(sys.argv) > 2 else 6
MIN_MV = 3900
me = os.path.abspath(__file__)
dead = subprocess.Popen(["setsid", "sh", "-c", "sleep %d; python3 %s --restore" % (int(max_h * 3600 + 900), me)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
done = {"why": None}
def stop(why):
    hiz(False)
    try:
        os.killpg(dead.pid, signal.SIGTERM)
    except Exception:
        pass
    mv, ma = bat()
    log("input restored: %s (vbat %d mV, ibat %d mA)" % (why, mv, ma))
signal.signal(signal.SIGTERM, lambda *_: (stop("signal"), sys.exit(1)))
signal.signal(signal.SIGINT, lambda *_: (stop("signal"), sys.exit(1)))

mv0, ma0 = bat()
log("start: vbat %d mV ibat %d mA, target %d mV, max %.1f h, dead-man pid %d" % (mv0, ma0, target, max_h, dead.pid))
if mv0 <= target:
    stop("already at or below target"); sys.exit(0)
hiz(True)
time.sleep(20)
mv, ma = bat()
if ma < 40:                                          # not discharging (positive = discharge) -> abort
    stop("input cut not confirmed (ibat %d mA)" % ma); sys.exit(2)
log("input cut confirmed: vbat %d mV ibat %d mA" % (mv, ma))
t0 = time.time()
try:
    while True:
        time.sleep(30)
        mv, ma = bat()
        log("vbat %d mV ibat %d mA (%.0f min)" % (mv, ma, (time.time() - t0) / 60))
        if mv <= target:
            stop("target reached"); break
        if mv < MIN_MV:
            stop("below %d mV safety floor" % MIN_MV); break
        if time.time() - t0 > max_h * 3600:
            stop("max time"); break
except Exception as e:
    stop("error: %s" % e); raise
