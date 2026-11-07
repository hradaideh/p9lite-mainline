#!/bin/sh
# Runs INSIDE p9build: build Huawei's Hi1102 driver (vendor 4.4 tree) against linux 7.3.1 and inventory errors.
set -u
K=/work/linux-7.3.1; O=${O:-/work/out7mod}; V=/work/vendor
if [ ! -f $O/.config ]; then
  cd $K && make O=$O ARCH=arm64 defconfig >/dev/null
  scripts/config --file $O/.config -e MODULES -e CFG80211 -e MAC80211 -e WLAN -e WIRELESS -e MMC -e PM_WAKELOCKS
  make O=$O ARCH=arm64 olddefconfig >/dev/null
  make O=$O ARCH=arm64 -j8 modules_prepare > /work/out7mod-prep.log 2>&1 || { echo prep failed; tail -5 /work/out7mod-prep.log; exit 1; }
fi
# vendor headers that do not exist in mainline (no old kernel core headers)
if [ ! -d /work/shim ]; then
  mkdir -p /work/shim
  cd $V && find include -type f | while read f; do [ -e $K/$f ] || { mkdir -p /work/shim/$(dirname $f); cp $f /work/shim/$f; }; done
  grep -oE 'CONFIG_[A-Z0-9_]+=y' /work/vendor-config 2>/dev/null > /dev/null
fi
# vendor-only CONFIG symbols that the running vendor kernel had enabled
python3 - <<'PY'
import re,os
cfg=open('/work/vendor.config').read() if os.path.exists('/work/vendor.config') else ''
ms=set()
for d,_,fs in os.walk('/work/linux-7.3.1'):
    for f in fs:
        if f.startswith('Kconfig'):
            for l in open(os.path.join(d,f),errors='ignore'):
                m=re.match(r'\s*(?:menu)?config\s+(\w+)',l)
                if m: ms.add(m.group(1))
h=open('/work/shim/vendor_config.h','w'); mk=open('/work/shim/vendor_config.mk','w')
for m in re.finditer(r'^CONFIG_(\w+)=(.*)$',cfg,re.M):
    k,v=m.group(1),m.group(2)
    if k in ms: continue
    if v=='y': h.write(f'#define CONFIG_{k} 1\n'); mk.write(f'CONFIG_{k}=m\n')
    elif v!='m': h.write(f'#define CONFIG_{k} {v}\n'); mk.write(f'CONFIG_{k}={v}\n')
print('vendor-only symbols written')
PY
find $V/drivers $V/include/linux/hisi $V/include/soc -name '*.h' -printf '%h\n' 2>/dev/null | sort -u | sed 's#^#-idirafter #' | tr '\n' ' ' > /work/shim/vdirs.flags
P=/work/hi1102

# every header directory of the driver itself (its Makefiles add these via its own paths)
find $P -name '*.h' -printf '%h\n' | sort -u | while read d; do echo "-I$d"; [ -d "$d/arch" ] && true; done | tr '\n' ' ' > /work/shim/wifidirs.flags
for d in $(find $P -type d -name arch); do echo "-I$(dirname $d)"; done | sort -u | tr '\n' ' ' >> /work/shim/wifidirs.flags
cd $K
make O=$O ARCH=arm64 M=$P -k -j8 \
  KCFLAGS="-include /work/shim/vendor_config.h -idirafter /work/shim/include -I$P -Wno-error -w -include /work/compat/p9_compat.h -idirafter /work/compat -idirafter /work/vendor/drivers -idirafter /work/vendor/include @/work/shim/wifidirs.flags" \
  $(cat /work/shim/vendor_config.mk) HI1102_MAKE_FLAG=1 HI1102_DRIVER_SRC_PATH=$P/hisi modules > /work/port/wifi.log 2>&1
c=$(find $P -name '*.c' | wc -l); ok=$(find $P -name '*.o' ! -name '*.mod.o' | wc -l)
echo "c-files=$c compiled-ok=$ok"
echo "--- error classes:"
grep -hE 'error:' /work/port/wifi.log | sed -E 's/.*error: //' | sed -E "s/'[^']*'/X/g" | sort | uniq -c | sort -rn | head -30
echo "--- most-hit symbols:"
grep -hE 'error:' /work/port/wifi.log | grep -oE "'[a-z_0-9]+'" | sort | uniq -c | sort -rn | head -30
