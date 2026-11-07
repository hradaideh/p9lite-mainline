#!/usr/bin/env python3
# Round-2 port of the Hi1102 driver to 7.3.1. Byte-level (sources are GBK), every edit asserts its match count.
import re, sys
R = '/work/hi1102/hisi/'

def edit(path, pairs):
    p = R + path
    d = open(p, 'rb').read()
    for old, new, want in pairs:
        if isinstance(old, re.Pattern):
            d, n = old.subn(new, d)
        else:
            n = d.count(old)
            d = d.replace(old, new)
        if n != want:
            sys.exit(f'{path}: expected {want} got {n} for {old!r:.80}')
    open(p, 'wb').write(d)
    print('ok', path)

def no_wext(d_count):
    # comment out WEXT handler hookup: line-wise #if 0, avoids nesting /* */
    return (re.compile(rb'^([ \t]*pst_net_dev->wireless_handlers[^\n]*)$', re.M),
            rb'#if 0 /* p9: WEXT removed */\n\1\n#endif', d_count)

edit('platform/oal/oal_cfg80211.c', [
    (b'cfg80211_roamed(pst_net_device->ieee80211_ptr, &__ri', b'cfg80211_roamed(pst_net_device, &__ri', 1),
])

edit('platform/oal/oal_sdio_host.c', [(b'st_wakelock.ws.name', b'st_wakelock.ws->name', 1)])

edit('platform/oal/oal_hcc_test.c', [
    (b'hi_sdio->func->card->host->claimer->comm)',
     b'(hi_sdio->func->card->host->claimer->task ? hi_sdio->func->card->host->claimer->task->comm : "?"))', 1),
])

# sk_buff.users is refcount_t since 4.13
edit('platform/oal/oal_mem.c', [
    (re.compile(rb'oal_atomic_read\(&([^()]*?->users)\)'), rb'refcount_read(&\1)', 3),
    (re.compile(rb'oal_atomic_set\(&([^(),]*?->users), 1\)'), rb'refcount_set(&\1, 1)', 2),
])

edit('wifi/wal/wal_linux_scan.c', [(b'    struct timespec ts;', b'    struct timespec64 ts;', 1)])

edit('platform/pm/plat_firmware.c', [(b'kernel_read(fp, fp->f_pos, ', b'p9_kernel_read_at(fp, fp->f_pos, ', 2)])
edit('common/customize/hisi_ini.c', [(b'kernel_read(fp, fp->f_pos, ', b'p9_kernel_read_at(fp, fp->f_pos, ', 1)])

edit('wifi/hmac/hmac_auto_adjust_freq.c', [(b'    g_pst_wifi_auto_ddr->pm_qos_class = 0;\n', b'', 1)])

# timers: timer_setup + container_of trampolines (the old callbacks took the owner pointer as `data`)
edit('platform/pm/plat_pm_wlan.c', [
    (b'void wlan_pm_wdg_timeout(struct wlan_pm_s *pm_data);\n',
     b'void wlan_pm_wdg_timeout(struct wlan_pm_s *pm_data);\n'
     b'static void p9_wlan_wdg_cb(struct timer_list *t)\n'
     b'{ wlan_pm_wdg_timeout(container_of(t, struct wlan_pm_s, st_watchdog_timer)); }\n', 1),
    (b'    init_timer(&pst_wlan_pm->st_watchdog_timer);\n'
     b'    pst_wlan_pm->st_watchdog_timer.data        = (unsigned long)pst_wlan_pm;\n'
     b'    pst_wlan_pm->st_watchdog_timer.function    = (void *)wlan_pm_wdg_timeout;\n',
     b'    timer_setup(&pst_wlan_pm->st_watchdog_timer, p9_wlan_wdg_cb, 0);\n', 1),
])

edit('platform/pm/plat_pm.c', [
    (b'waitqueue_active(&pm_data->host_wkup_dev_comp.wait)', b'swait_active(&pm_data->host_wkup_dev_comp.wait)', 1),
    (b'test_bit(ASYNCB_SUSPENDED, (volatile unsigned long*)&(ps_core_d->tty->port->flags))',
     b'tty_port_suspended(ps_core_d->tty->port)', 1),
    (b'    init_timer(&pm_data->dev_ack_timer);\n'
     b'    pm_data->dev_ack_timer.function = devack_timer_expire;\n'
     b'    pm_data->dev_ack_timer.data     = (unsigned long)pm_data;\n',
     b'    timer_setup(&pm_data->dev_ack_timer, p9_devack_timer_cb, 0);\n', 1),
    (b'    init_timer(&pm_data->bfg_timer);\n'
     b'    pm_data->bfg_timer.function = bfg_timer_expire;\n'
     b'    pm_data->bfg_timer.data     = (unsigned long)pm_data;\n',
     b'    timer_setup(&pm_data->bfg_timer, p9_bfg_timer_cb, 0);\n', 1),
    (b'STATIC void devack_timer_expire(uint64 data)\n',
     b'STATIC void devack_timer_expire(uint64 data);\n'
     b'static void p9_devack_timer_cb(struct timer_list *t)\n'
     b'{ devack_timer_expire((uint64)container_of(t, struct pm_drv_data, dev_ack_timer)); }\n'
     b'static void p9_bfg_timer_cb(struct timer_list *t)\n'
     b'{ bfg_timer_expire((uint64)container_of(t, struct pm_drv_data, bfg_timer)); }\n'
     b'STATIC void devack_timer_expire(uint64 data)\n', 1),
])

# procfs: file_operations -> proc_ops (5.6)
p = R + 'common/oneimage/oneimage.c'
d = open(p, 'rb').read()
a = d.index(b'static const struct file_operations hwconn_proc_fops[]= {')
b = d.index(b'};', a) + 2
blk = d[a:b].replace(b'struct file_operations', b'struct proc_ops')
blk = re.sub(rb'[ \t]*\.owner = THIS_MODULE,\n', b'', blk)
blk, n = re.subn(rb'\.read = ', b'.proc_read = ', blk)
assert n >= 4, n
open(p, 'wb').write(d[:a] + blk + d[b:]); print('ok oneimage.c', n)

# ndo_select_queue: (dev, skb, sb_dev) since 4.19/5.2
edit('wifi/wal/wal_linux_flowctl.c', [(b'void *accel_priv, select_queue_fallback_t fallback)', b'struct net_device *sb_dev)', 1)])
edit('wifi/wal/wal_linux_flowctl.h', [(b'void *accel_priv, select_queue_fallback_t fallback)', b'struct net_device *sb_dev)', 1)])

edit('wifi/wal/wal_linux_ioctl.c', [no_wext(2)])

# cfg80211 ops: thin adapters with the 7.3.1 prototypes calling the vendor functions unchanged
WRAP = b'''
/* p9: cfg80211_ops adapters for 7.3.1 (wdev instead of netdev, link ids, cookies by value). */
static int p9_add_key(struct wiphy *w, struct wireless_dev *wd, int link, u8 idx, bool pw, const u8 *mac, struct key_params *kp)
{ return wal_cfg80211_add_key(w, wd->netdev, idx, pw, mac, kp); }
static int p9_get_key(struct wiphy *w, struct wireless_dev *wd, int link, u8 idx, bool pw, const u8 *mac, void *ck, void (*cb)(void *, struct key_params *))
{ return wal_cfg80211_get_key(w, wd->netdev, idx, pw, mac, ck, cb); }
static int p9_del_key(struct wiphy *w, struct wireless_dev *wd, int link, u8 idx, bool pw, const u8 *mac)
{ return wal_cfg80211_remove_key(w, wd->netdev, idx, pw, mac); }
static int p9_set_default_key(struct wiphy *w, struct net_device *nd, int link, u8 idx, bool uc, bool mc)
{ return wal_cfg80211_set_default_key(w, nd, idx, uc, mc); }
static int p9_set_default_mgmt_key(struct wiphy *w, struct wireless_dev *wd, int link, u8 idx)
{ return wal_cfg80211_set_default_mgmt_key(w, wd->netdev, idx); }
static int p9_set_wiphy_params(struct wiphy *w, int radio, u32 changed)
{ return wal_cfg80211_set_wiphy_params(w, changed); }
static int p9_change_beacon(struct wiphy *w, struct net_device *nd, struct cfg80211_ap_update *u)
{ return wal_cfg80211_change_beacon(w, nd, &u->beacon); }
static int p9_stop_ap(struct wiphy *w, struct net_device *nd, unsigned int link)
{ return wal_cfg80211_stop_ap(w, nd); }
static int p9_sched_scan_stop(struct wiphy *w, struct net_device *nd, u64 reqid)
{ return wal_cfg80211_sched_scan_stop(w, nd); }
static int p9_change_virtual_intf(struct wiphy *w, struct net_device *nd, enum nl80211_iftype t, struct vif_params *vp)
{ return wal_cfg80211_change_virtual_intf(w, nd, t, &vp->flags, vp); }
static int p9_add_station(struct wiphy *w, struct wireless_dev *wd, const u8 *mac, struct station_parameters *sp)
{ return wal_cfg80211_add_station(w, wd->netdev, mac, sp); }
static int p9_del_station(struct wiphy *w, struct wireless_dev *wd, struct station_del_parameters *dp)
{ return wal_cfg80211_del_station(w, wd->netdev, dp); }
static int p9_change_station(struct wiphy *w, struct wireless_dev *wd, const u8 *mac, struct station_parameters *sp)
{ return wal_cfg80211_change_station(w, wd->netdev, mac, sp); }
static int p9_get_station(struct wiphy *w, struct wireless_dev *wd, const u8 *mac, struct station_info *si)
{ return wal_cfg80211_get_station(w, wd->netdev, mac, si); }
static int p9_dump_station(struct wiphy *w, struct wireless_dev *wd, int i, u8 *mac, struct station_info *si)
{ return wal_cfg80211_dump_station(w, wd->netdev, i, mac, si); }
/* ponytail: cfg80211 now owns ROC/mgmt_tx cookies; the driver's own cookie is discarded.
 * Fine for STA (driver SME via .connect); P2P events would carry the wrong cookie. */
static int p9_remain_on_channel(struct wiphy *w, struct wireless_dev *wd, struct ieee80211_channel *ch, unsigned int dur, u64 cookie, const u8 *rx)
{ u64 c = cookie; return wal_cfg80211_remain_on_channel(w, wd, ch, dur, &c); }
static int p9_mgmt_tx(struct wiphy *w, struct wireless_dev *wd, struct cfg80211_mgmt_tx_params *mp, u64 cookie)
{ u64 c = cookie; return wal_cfg80211_mgmt_tx(w, wd, mp, &c); }
static int p9_set_bitrate_mask(struct wiphy *w, struct net_device *nd, unsigned int link, const u8 *peer, const struct cfg80211_bitrate_mask *m)
{ return wal_cfg80211_set_bitrate_mask(w, nd, peer, m); }
static struct wireless_dev *p9_add_virtual_intf(struct wiphy *w, const char *name, unsigned char nat, enum nl80211_iftype t, struct vif_params *vp)
{ return wal_cfg80211_add_virtual_intf(w, name, nat, t, &vp->flags, vp); }

'''
OPS = [(b'wal_cfg80211_' + o, b'p9_' + o) for o in [
    b'add_key', b'get_key', b'set_default_mgmt_key', b'set_wiphy_params', b'change_beacon', b'stop_ap',
    b'sched_scan_stop', b'change_virtual_intf', b'add_station', b'del_station', b'change_station',
    b'get_station', b'dump_station', b'remain_on_channel', b'mgmt_tx', b'set_bitrate_mask', b'add_virtual_intf']]
p = R + 'wifi/wal/wal_linux_cfg80211.c'
d = open(p, 'rb').read()
d, n = re.subn(rb'^([ \t]*pst_net_dev->wireless_handlers[^\n]*)$', rb'#if 0 /* p9: WEXT removed */\n\1\n#endif', d, flags=re.M); assert n == 1, n
n = d.count(b'ieee80211_ptr->preset_chandef.'); assert n == 3, n
d = d.replace(b'ieee80211_ptr->preset_chandef.', b'ieee80211_ptr->u.ap.preset_chandef.')
old = b'            pst_wiphy->flags |= WIPHY_FLAG_SUPPORTS_SCHED_SCAN;'
assert d.count(old) == 1; d = d.replace(old, b'            pst_wiphy->max_sched_scan_reqs = 1;')
head = b'#if (_PRE_OS_VERSION_LINUX == _PRE_OS_VERSION)\nOAL_STATIC oal_cfg80211_ops_stru  g_wal_cfg80211_ops =\n{\n'
a = d.index(head); b = d.index(b'};', a)
tbl = d[a:b]
tbl, n = re.subn(rb'\n[ \t]*\.mgmt_frame_register[^\n]*', b'', tbl); assert n == 1, n
for o, w in OPS:
    tbl, n = re.subn(rb'(=\s*)' + o + rb',', rb'\g<1>' + w + b',', tbl); assert n == 1, (o, n)
tbl, n = re.subn(rb'(\.del_key\s*=\s*)wal_cfg80211_remove_key,', rb'\1p9_del_key,', tbl); assert n == 1
tbl, n = re.subn(rb'(\.set_default_key\s*=\s*)wal_cfg80211_set_default_key,', rb'\1p9_set_default_key,', tbl); assert n == 1
d = d[:a] + b'#if (_PRE_OS_VERSION_LINUX == _PRE_OS_VERSION)\n' + WRAP + tbl[len(b'#if (_PRE_OS_VERSION_LINUX == _PRE_OS_VERSION)\n'):] + d[b:]
open(p, 'wb').write(d); print('ok wal_linux_cfg80211.c')
