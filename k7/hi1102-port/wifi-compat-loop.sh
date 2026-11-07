#!/bin/sh
# Runs INSIDE p9build. Iteratively add compat headers for headers removed from mainline,
# rebuilding the Hi1102 driver until no "No such file" errors remain (max 12 rounds).
C=/work/compat; mkdir -p $C/asm $C/linux
map() {  # header -> content
  case "$1" in
    stdarg.h) echo '#include <linux/stdarg.h>';;
    stdbool.h) echo '#include <linux/types.h>';;
    asm/system.h) echo '/* removed in 3.4; contents moved elsewhere */ #include <asm/barrier.h>';;
    linux/wakelock.h) cat <<'EOF'
#ifndef _COMPAT_WAKELOCK_H
#define _COMPAT_WAKELOCK_H
#include <linux/pm_wakeup.h>
#include <linux/slab.h>
#define WAKE_LOCK_SUSPEND 0
struct wake_lock { struct wakeup_source *ws; };
static inline void wake_lock_init(struct wake_lock *l, int type, const char *name)
{ l->ws = wakeup_source_register(NULL, name); }
static inline void wake_lock_destroy(struct wake_lock *l) { wakeup_source_unregister(l->ws); }
static inline void wake_lock(struct wake_lock *l) { __pm_stay_awake(l->ws); }
static inline void wake_lock_timeout(struct wake_lock *l, long t) { __pm_wakeup_event(l->ws, jiffies_to_msecs(t)); }
static inline void wake_unlock(struct wake_lock *l) { __pm_relax(l->ws); }
static inline int wake_lock_active(struct wake_lock *l) { return l->ws && l->ws->active; }
#endif
EOF
    ;;
    *) echo "/* compat stub for $1 */";;
  esac
}
for round in 1 2 3 4 5 6 7 8 9 10 11 12; do
  sh /work/wifi-inventory.sh > /work/port/inv-round.txt 2>&1
  missing=$(grep -hoE "fatal error: [^:]+: No such file" /work/port/wifi.log | sed -E 's/fatal error: (.*): No such file/\1/' | sort -u)
  ok=$(grep -oE "compiled-ok=[0-9]+" /work/port/inv-round.txt)
  echo "round $round: $ok missing=[$(echo $missing | tr '\n' ' ')]"
  [ -z "$missing" ] && break
  for h in $missing; do
    if [ ! -e $C/$h ]; then mkdir -p $C/$(dirname $h); map "$h" > $C/$h; fi
  done
done
cat /work/port/inv-round.txt | tail -45
