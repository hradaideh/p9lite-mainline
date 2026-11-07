#!/usr/bin/env python3
# Round 6 (found on hardware): devm_clk_get returns ERR_PTR, never NULL; 7.3.1 has no Hi6250 clock
# driver so "clk_pmu32kb" is -ENOENT and the vendor NULL check let it reach clk_prepare() -> oops.
p = '/work/hi1102/hisi/platform/board/board.c'
d = open(p, 'rb').read()
old = b'\tclk = devm_clk_get(dev, "clk_pmu32kb");\n'
assert d.count(old) == 1
d = d.replace(old, old +
    b'\tif (IS_ERR(clk)) {\n'
    b'\t\t/* p9: no Hi6250 clock driver in mainline; p9test turns on PMIC 0x121 bit 1 (clk_pmu32kb) */\n'
    b'\t\tPS_PRINT_INFO("32k clk not provided (%ld), assuming PMIC already enables it\\n", PTR_ERR(clk));\n'
    b'\t\tg_board_info.clk_32k = NULL;\n'
    b'\t\treturn BOARD_SUCC;\n'
    b'\t}\n')
open(p, 'wb').write(d); print('ok')
