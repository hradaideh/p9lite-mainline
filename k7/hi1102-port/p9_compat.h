/* SPDX-License-Identifier: GPL-2.0 */
/*
 * p9_compat.h - force-included when building the Huawei Hi1102 driver (written for
 * Linux 4.4) against Linux 7.x. Maps removed kernel APIs onto their replacements.
 */
#ifndef _P9_COMPAT_H
#define _P9_COMPAT_H

#include <linux/types.h>
#include <linux/time64.h>
#include <linux/timekeeping.h>
#include <linux/sched/clock.h>
#include <linux/string.h>
#include <linux/version.h>

/* struct timeval / do_gettimeofday: removed in 5.6 (y2038) */
#define timeval __kernel_old_timeval
static inline void do_gettimeofday(struct __kernel_old_timeval *tv)
{
	struct timespec64 ts;

	ktime_get_real_ts64(&ts);
	tv->tv_sec = ts.tv_sec;
	tv->tv_usec = ts.tv_nsec / 1000;
}

/* set_fs()/get_fs()/KERNEL_DS: removed (5.10 on arm64); kernel_read/write no longer need them */
typedef int mm_segment_t;
#define KERNEL_DS 0
#define USER_DS 0
#define get_fs() 0
#define get_ds() 0
#define set_fs(x) do { (void)(x); } while (0)

/* misc renames */
#define random_ether_addr(a) eth_random_addr(a)
#define netif_rx_ni(skb) netif_rx(skb)

/* timers: del_timer* renamed in 6.2/6.15 */
#define del_timer(t) timer_delete(t)
#define del_timer_sync(t) timer_delete_sync(t)

/* cfg80211 band enum: ieee80211_band -> nl80211_band (4.7) */
#include <uapi/linux/nl80211.h>
#define ieee80211_band nl80211_band
#define IEEE80211_BAND_2GHZ NL80211_BAND_2GHZ
#define IEEE80211_BAND_5GHZ NL80211_BAND_5GHZ
#define IEEE80211_BAND_60GHZ NL80211_BAND_60GHZ
#define IEEE80211_NUM_BANDS NUM_NL80211_BANDS
#define RATE_INFO_FLAGS_60G RATE_INFO_FLAGS_DMG

/* strncpy: removed from the kernel; keep its exact semantics (zero pad, no forced NUL) */
static inline char *p9_strncpy(char *dst, const char *src, size_t n)
{
	size_t i = 0;

	for (; i < n && src[i]; i++)
		dst[i] = src[i];
	for (; i < n; i++)
		dst[i] = '\0';
	return dst;
}
#define strncpy(d, s, n) p9_strncpy(d, s, n)

/* rtc / time helpers */
#include <linux/rtc.h>
#define rtc_time_to_tm(t, tm) rtc_time64_to_tm((time64_t)(t), tm)
#define get_monotonic_boottime(ts) ktime_get_boottime_ts64(ts)

/* uaccess: access_ok lost its type argument (5.0) */
#define VERIFY_READ 0
#define VERIFY_WRITE 1
#include <linux/uaccess.h>

/* panic_notifier_list moved (5.14) */
#include <linux/panic_notifier.h>


/* ===== 4.4 -> 7.x port, round 2 ===== */

/* mmc_power_save/restore_host removed in 5.1. plat_pm.c's sdio_reinit() power-cycles the
 * Hi1102 through its GPIO, then calls these to re-initialise the fresh card (every wlan0 open).
 * Save is a no-op (the GPIO already cut power); restore = claimed mmc_hw_reset(), which for a
 * single-function SDIO card power-cycles the host and re-runs card init (CMD5/3/7, bus width). */
#include <linux/mmc/host.h>
#include <linux/mmc/card.h>
#include <linux/mmc/sdio_func.h>
static inline int mmc_power_save_host(struct mmc_host *h) { (void)h; return 0; }
static inline int mmc_power_restore_host(struct mmc_host *h)
{
	struct sdio_func *f = h->card ? h->card->sdio_func[0] : NULL;
	int ret;

	if (!f)
		return -ENODEV;
	sdio_claim_host(f);
	ret = mmc_hw_reset(h->card);
	sdio_release_host(f);
	return ret;
}

/* kernel_read(file, off, buf, n) became kernel_read(file, buf, n, &pos) in 4.14.
 * Call sites are switched to this helper explicitly. */
#include <linux/fs.h>
static inline ssize_t p9_kernel_read_at(struct file *f, loff_t off, void *buf, size_t n)
{
	return kernel_read(f, buf, n, &off);
}

/* cfg80211_sched_scan_results gained a request id (4.12); single request => 0 */
#include <net/cfg80211.h>
static inline void p9_sched_scan_results(struct wiphy *w) { cfg80211_sched_scan_results(w, 0); }
#define cfg80211_sched_scan_results(w) p9_sched_scan_results(w)

/* pm_qos memory-throughput class removed in 5.7: DDR frequency votes become no-ops */
#include <linux/pm_qos.h>
#define PM_QOS_MEMORY_THROUGHPUT               0
#define PM_QOS_MEMORY_THROUGHPUT_DEFAULT_VALUE 0
static inline void pm_qos_add_request(struct pm_qos_request *r, int c, s32 v) { }
static inline void pm_qos_update_request(struct pm_qos_request *r, s32 v) { }
static inline void pm_qos_remove_request(struct pm_qos_request *r) { }

/* fbdev blank events no longer exist; the notifier compiles but never fires */
#define FB_EVENT_BLANK       0x09
#define FB_EARLY_EVENT_BLANK 0x10

/* legacy integer GPIO API (needs CONFIG_GPIOLIB_LEGACY) */
#include <linux/gpio/legacy.h>

/* sched_setscheduler() unexported for modules in 5.9: map to sched_set_fifo/normal */
#include <linux/sched.h>
#include <uapi/linux/sched.h>
static inline int p9_sched_setscheduler(struct task_struct *p, int policy, const void *sp)
{
	if (policy == SCHED_FIFO || policy == SCHED_RR)
		sched_set_fifo(p);
	else
		sched_set_normal(p, 0);
	return 0;
}
#define sched_setscheduler(p, pol, sp) p9_sched_setscheduler(p, pol, sp)

/* kallsyms_lookup_name unexported in 5.7; only a debug "poke global by name" command uses it */
#include <linux/kallsyms.h>
#define kallsyms_lookup_name(n) ((void)(n), 0UL)

#endif /* _P9_COMPAT_H */
