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

#endif /* _P9_COMPAT_H */
