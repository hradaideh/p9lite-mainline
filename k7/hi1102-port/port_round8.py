#!/usr/bin/env python3
# Round 8 (found on hardware): wiphy_apply_custom_regulatory() takes rtnl in 7.x. wal_regdomain_update()
# runs from ndo_open (and the reg notifier), both already under rtnl -> the task deadlocks on itself.
# Run the reset/apply/save sequence from a worker; pst_regdom points into the static regdb table.
p = '/work/hi1102/hisi/wifi/wal/wal_linux_ioctl.c'
d = open(p, 'rb').read()
call = (b'        wal_cfg80211_reset_bands();\n'
        b'        oal_wiphy_apply_custom_regulatory(pst_device->pst_wiphy, pst_regdom);\n'
        b'        wal_cfg80211_save_bands();\n')
fn = b'oal_int32  wal_regdomain_update(oal_net_device_stru *pst_net_dev, oal_int8 *pc_country)\n{'
import re
# a GBK comment sits between apply and save; match the whole span
rx = re.compile(rb'        wal_cfg80211_reset_bands\(\);\n        oal_wiphy_apply_custom_regulatory\(pst_device->pst_wiphy, pst_regdom\);\n(?:[^\n]*\n){0,4}?\s*wal_cfg80211_save_bands\(\);\n')
m = rx.findall(d)
assert len(m) == 1 and d.count(fn) == 1, (len(m), d.count(fn))
print(m[0][-160:])
d = rx.sub(b'        p9_regdom_apply_async(pst_device->pst_wiphy, pst_regdom);\n', d)
d = d.replace(fn, b'''/* p9: wiphy_apply_custom_regulatory() takes rtnl since 6.x, callers here already hold it */
static struct wiphy *p9_reg_wiphy;
static const struct ieee80211_regdomain *p9_reg_rd;
static void p9_regdom_apply_fn(struct work_struct *w)
{
    wal_cfg80211_reset_bands();
    wiphy_apply_custom_regulatory(p9_reg_wiphy, p9_reg_rd);
    wal_cfg80211_save_bands();
}
static DECLARE_WORK(p9_reg_work, p9_regdom_apply_fn);
static void p9_regdom_apply_async(struct wiphy *wiphy, const struct ieee80211_regdomain *rd)
{
    p9_reg_wiphy = wiphy;
    p9_reg_rd = rd;
    schedule_work(&p9_reg_work);    /* ponytail: not flushed on module unload; unload is unsupported anyway */
}

''' + fn)
open(p, 'wb').write(d); print('ok')
