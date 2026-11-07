#!/usr/bin/env python3
# Round 4: modpost rejects exporting static symbols (5.x+); NFC probe is Huawei-only.
import re, sys
R = '/work/hi1102/hisi/'
def edit(path, pairs):
    d = open(R + path, 'rb').read()
    for old, new, want in pairs:
        n = d.count(old)
        if n != want: sys.exit(f'{path}: want {want} got {n}: {old!r}')
        d = d.replace(old, new)
    open(R + path, 'wb').write(d); print('ok', path)
# exported static inline header functions: each user has its own copy, drop the export
edit('platform/frw/frw_event_main.c', [(b'oal_module_symbol(frw_event_alloc);\n', b'', 1),
                                       (b'oal_module_symbol(frw_event_free);\n', b'', 1),
                                       (b'OAL_STATIC oal_void  frw_event_get_info_from_event_queue(', b'oal_void  frw_event_get_info_from_event_queue(', 1)])
edit('wifi/dmac/mac_resource.c', [(b'oal_module_symbol(mac_res_get_dev);\n', b'', 1)])
# exported static definitions: make them global so the other module can still link to them
edit('platform/oal/oal_mem.c', [(b'OAL_STATIC oal_netbuf_stru *g_pst_netbuf_base_addr[', b'oal_netbuf_stru *g_pst_netbuf_base_addr[', 1),
                                (b'OAL_STATIC oal_netbuf_stru *g_pst_sdt_netbuf_base_addr[', b'oal_netbuf_stru *g_pst_sdt_netbuf_base_addr[', 1),
                                (b'OAL_STATIC oal_mempool_tx_dscr_addr    g_st_tx_dscr_addr;', b'oal_mempool_tx_dscr_addr    g_st_tx_dscr_addr;', 1)])
edit('platform/oam/oam_event.c', [(b'OAL_STATIC oal_uint32  oam_ota_report_to_std(', b'oal_uint32  oam_ota_report_to_std(', 1)])
edit('wifi/dmac/mac_vap.c', [(b'OAL_STATIC oal_void  mac_init_mib(', b'oal_void  mac_init_mib(', 1)])
edit('wifi/wal/wal_linux_ioctl.c', [(b'OAL_STATIC oal_int32  wal_hipriv_proc_write(', b'oal_int32  wal_hipriv_proc_write(', 2)])
edit('common/oneimage/oneimage.c', [(b'isMyNfcChip(NFC_CHIP_TYPE_HI110X)', b'0 /* p9: no Hi110x NFC on VNS-L21 */', 1)])
