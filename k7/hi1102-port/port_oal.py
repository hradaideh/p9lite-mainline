#!/usr/bin/env python3
# Port the Hi1102 OAL (OS abstraction) headers from Linux 4.4 to 7.x APIs.
# Files are GBK-encoded; operate on bytes via latin-1 so nothing else changes.
import sys
B = '/work/hi1102/hisi/platform/inc/oal/linux/arch/'

def patch(fn, pairs):
    p = B + fn
    s = open(p, encoding='latin-1').read()
    for old, new in pairs:
        if old not in s:
            sys.exit(f'{fn}: pattern not found:\n{old}')
        s = s.replace(old, new)
    open(p, 'w', encoding='latin-1').write(s)
    print(f'{fn}: {len(pairs)} changes')

# ---------------------------------------------------------------- oal_schedule.h
patch('oal_schedule.h', [
    ('typedef struct timer_list              oal_timer_list_stru;\n',
     '/* oal_timer_list_stru is defined after oal_timer_func below (timer_list lost .data in 4.15) */\n'),
    ('typedef wait_queue_t         oal_wait_queue_stru;', 'typedef wait_queue_entry_t   oal_wait_queue_stru;'),
    ('typedef void (*oal_timer_func)(oal_uint);\n',
     '''typedef void (*oal_timer_func)(oal_uint);
/* p9 port: wrapper keeping the old (function, unsigned long data) timer semantics */
typedef struct {
    struct timer_list timer;
    oal_timer_func    func;
    oal_uint          data;
} oal_timer_list_stru;
static inline void oal_timer_trampoline(struct timer_list *t)
{
    oal_timer_list_stru *w = container_of(t, oal_timer_list_stru, timer);
    w->func(w->data);
}
'''),
    ('''    init_timer(pst_timer);
    pst_timer->expires = jiffies + msecs_to_jiffies(ul_delay);
    pst_timer->function = p_func;
    pst_timer->data = ui_arg;''',
     '''    timer_setup(&pst_timer->timer, oal_timer_trampoline, 0);
    pst_timer->func = p_func;
    pst_timer->data = ui_arg;
    pst_timer->timer.expires = jiffies + msecs_to_jiffies(ul_delay);'''),
    ('return del_timer(pst_timer);', 'return timer_delete(&pst_timer->timer);'),
    ('return del_timer_sync(pst_timer);', 'return timer_delete_sync(&pst_timer->timer);'),
    ('    add_timer(pst_timer);', '    add_timer(&pst_timer->timer);'),
    ('return mod_timer(pst_timer, (jiffies + msecs_to_jiffies(ui_delay)));',
     'return mod_timer(&pst_timer->timer, (jiffies + msecs_to_jiffies(ui_delay)));'),
    ('''    pst_timer->expires = jiffies + msecs_to_jiffies(ui_delay);
    add_timer_on(pst_timer, cpu);''',
     '''    pst_timer->timer.expires = jiffies + msecs_to_jiffies(ui_delay);
    add_timer_on(&pst_timer->timer, cpu);'''),
    ('''    struct timespec ts;

    getnstimeofday(&ts);''',
     '''    struct timespec64 ts;

    ktime_get_real_ts64(&ts);'''),
    ('''    struct timeval tv;
    oal_uint64 curr_time;

    do_gettimeofday(&tv);
    curr_time = tv.tv_usec;''',
     '''    struct timespec64 tv;
    oal_uint64 curr_time;

    ktime_get_real_ts64(&tv);
    curr_time = tv.tv_nsec / 1000;'''),
])

# ---------------------------------------------------------------- oal_net.h
patch('oal_net.h', [
    ('#define OAL_NETDEVICE_LAST_RX(_pst_dev)                     ((_pst_dev)->last_rx)',
     '/* net_device.last_rx removed in 4.11 */\n#define OAL_NETDEVICE_LAST_RX(_pst_dev)                     (*({ static unsigned long __p9_last_rx; &__p9_last_rx; }))'),
    ('#define OAL_NETDEVICE_DESTRUCTOR(_pst_dev)                  ((_pst_dev)->destructor)',
     '/* net_device.destructor became priv_destructor + needs_free_netdev in 4.12 */\n#define OAL_NETDEVICE_DESTRUCTOR(_pst_dev)                  ((_pst_dev)->priv_destructor)'),
    ('enum ieee80211_band band)', 'enum nl80211_band band)'),
    ('case IEEE80211_BAND_2GHZ:', 'case NL80211_BAND_2GHZ:'),
    ('case IEEE80211_BAND_5GHZ:', 'case NL80211_BAND_5GHZ:'),
    ('oal_atomic_dec(&(pst_buf->users));', 'refcount_dec(&(pst_buf->users));'),
    ('oal_atomic_inc(&(pst_buf->users));', 'refcount_inc(&(pst_buf->users));'),
    ('return netif_rx_ni(pst_netbuf);', 'return netif_rx(pst_netbuf);'),
    ('return cpu_clock(UINT_MAX);', 'return local_clock();'),
    ('    cfg.cb_mutex = NULL;\n', ''),
])

# ---------------------------------------------------------------- oal_util.h
patch('oal_util.h', [
    ('   random_ether_addr(addr);', '   eth_random_addr(addr);'),
    ('return kernel_read(file, 0, pc_buf, ul_count);',
     '{ loff_t pos = 0; return kernel_read(file, pc_buf, ul_count, &pos); }'),
    ('return strncpy((oal_int8 *)pc_dest, pc_src, ul_len);',
     'strscpy_pad((char *)pc_dest, pc_src, ul_len); return pc_dest;'),
])

# ---------------------------------------------------------------- oal_kernel_file.h
patch('oal_kernel_file.h', [
    ('typedef mm_segment_t            oal_mm_segment_t;',
     '/* set_fs()/get_fs() are gone (5.10 arm64); kernel_read/kernel_write need no segment switch */\ntypedef int                     oal_mm_segment_t;'),
    ('    return  get_fs();', '    return 0;'),
    ('    return set_fs(fs);', '    (void)fs;'),
])
