#!/usr/bin/env python3
# Round 7 (found on hardware): since 5.3 every cfg80211 vendor command needs a netlink policy,
# else wiphy_register() WARNs and returns -EINVAL. These handlers all take raw blobs.
p = '/work/hi1102/hisi/wifi/wal/wal_linux_cfgvendor.c'
d = open(p, 'rb').read()
a = d.index(b'wal_vendor_cmds[] =')
b = d.index(b'};', a)
t = d[a:b]
n = t.count(b'.doit = wal_cfgvendor_')
assert n == 11, n
t = t.replace(b'.doit = wal_cfgvendor_', b'.policy = VENDOR_CMD_RAW_DATA,\n        .doit = wal_cfgvendor_')
open(p, 'wb').write(d[:a] + t + d[b:]); print('ok', n)
