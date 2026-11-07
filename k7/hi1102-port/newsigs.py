import re
s = open('/work/linux-7.3.1/include/net/cfg80211.h').read()
i = s.index('struct cfg80211_ops {')
body = s[i:s.index('\n};', i)]
want = ['add_key', 'get_key', 'del_key', 'set_default_key', 'set_default_mgmt_key', 'set_wiphy_params',
        'change_beacon', 'stop_ap', 'sched_scan_stop', 'change_virtual_intf', 'add_station', 'del_station',
        'change_station', 'get_station', 'dump_station', 'remain_on_channel', 'mgmt_tx',
        'update_mgmt_frame_registrations', 'set_bitrate_mask', 'add_virtual_intf', 'set_power_mgmt',
        'mgmt_tx_cancel_wait', 'flush_pmksa', 'set_pmksa', 'del_pmksa', 'start_ap', 'change_bss',
        'cancel_remain_on_channel', 'del_virtual_intf', 'start_p2p_device', 'stop_p2p_device',
        'update_ft_ies', 'abort_scan', 'connect', 'disconnect', 'scan', 'sched_scan_start', 'dump_survey']
for w in want:
    m = re.search(r'\n\t([^;]*?\(\*' + w + r'\)\((.*?)\));', body, re.S)
    print(w, '=>', re.sub(r'\s+', ' ', m.group(1)) if m else 'MISSING')
