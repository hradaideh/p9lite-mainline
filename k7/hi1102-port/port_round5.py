#!/usr/bin/env python3
# Round 5: bfgx + plat_uart back in the build (they hold the Wi-Fi exception/recovery code).
import sys
R = '/work/hi1102/hisi/'
def edit(path, pairs):
    d = open(R + path, 'rb').read()
    for old, new, want in pairs:
        n = d.count(old)
        if n != want: sys.exit(f'{path}: want {want} got {n}: {old!r}')
        d = d.replace(old, new)
    open(R + path, 'wb').write(d); print('ok', path)

edit('bfgx/bfgx_exception_rst.c', [
    (b'void  bfgx_beat_timer_expire(uint64 data);\n',
     b'void  bfgx_beat_timer_expire(uint64 data);\n'
     b'static void p9_bfgx_beat_cb(struct timer_list *t) { bfgx_beat_timer_expire(0); }\n', 1),
    (b'    init_timer(&p_exception_data->bfgx_beat_timer);\n'
     b'    p_exception_data->bfgx_beat_timer.function = bfgx_beat_timer_expire;\n',
     b'    timer_setup(&p_exception_data->bfgx_beat_timer, p9_bfgx_beat_cb, 0);\n', 1),
    (b'    p_exception_data->bfgx_beat_timer.data     = 0;\n', b'', 1),
])
edit('bfgx/bfgx_dev.c', [
    (b'access_ok(VERIFY_WRITE, puser, ', b'access_ok(puser, ', 1),
    (b'STATIC struct platform_driver ps_platform_driver = {',
     b'static void p9_ps_remove(struct platform_device *p) { ps_remove(p); }\n'
     b'STATIC struct platform_driver ps_platform_driver = {', 1),
    (b'        .remove     = ps_remove,\n', b'        .remove     = p9_ps_remove,\n', 1),
])
edit('platform/driver/plat_uart.c', [
    (b'g_uart_state.tty_stopped = tty->stopped;', b'g_uart_state.tty_stopped = tty->flow.stopped;', 1),
    (b'STATIC struct tty_ldisc_ops ps_ldisc_ops = {\n    .magic          = TTY_LDISC_MAGIC,\n',
     b'static void p9_tty_receive(struct tty_struct *t, const u8 *cp, const u8 *fp, size_t n)\n'
     b'{ ps_tty_receive(t, cp, (int8 *)fp, (int32)n); }\n'
     b'/* ldisc 35 is beyond NR_LDISCS (31) in 7.x; N_DEVELOPMENT is the out-of-tree slot */\n'
     b'STATIC struct tty_ldisc_ops ps_ldisc_ops = {\n    .num            = N_DEVELOPMENT,\n', 1),
    (b'    .receive_buf    = ps_tty_receive,\n', b'    .receive_buf    = p9_tty_receive,\n', 1),
    (b'    return tty_register_ldisc(N_HW_BFG, &ps_ldisc_ops);', b'    return tty_register_ldisc(&ps_ldisc_ops);', 1),
    (b'    return tty_unregister_ldisc(N_HW_BFG);', b'    tty_unregister_ldisc(&ps_ldisc_ops);\n    return 0;', 1),
])
