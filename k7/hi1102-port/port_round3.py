#!/usr/bin/env python3
# Round 3: platform_driver.remove returns void (6.11); legacy GPIO API lives in gpio/legacy.h.
p = '/work/hi1102/hisi/platform/board/board.c'
d = open(p, 'rb').read()
a = b'STATIC struct platform_driver hi110x_board_driver = {'
assert d.count(a) == 1 and d.count(b'.remove     = hi110x_board_remove,') == 1
d = d.replace(a, b'static void p9_board_remove(struct platform_device *p) { hi110x_board_remove(p); }\n' + a)
d = d.replace(b'.remove     = hi110x_board_remove,', b'.remove     = p9_board_remove,')
open(p, 'wb').write(d)
c = '/work/compat/p9_compat.h'
t = open(c).read()
if 'gpio/legacy.h' not in t:
    t = t.replace('#endif /* _P9_COMPAT_H */', '/* legacy integer GPIO API (needs CONFIG_GPIOLIB_LEGACY) */\n#include <linux/gpio/legacy.h>\n\n#endif /* _P9_COMPAT_H */')
    open(c, 'w').write(t)
print('ok')
