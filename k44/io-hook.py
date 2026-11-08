#!/usr/bin/env python3
"""Hook __raw_write{b,w,l} in the vendor 4.4 arch/arm64/include/asm/io.h for p9iotrace. Idempotent."""
import sys
p = sys.argv[1] + "/arch/arm64/include/asm/io.h"
s = open(p).read()
if "p9_iotrace" in s:
    sys.exit(0)
s = s.replace("#include <xen/xen.h>\n", "#include <xen/xen.h>\n\nextern int p9_iotrace_on;\n"
              "void p9_iotrace(u32 val, const volatile void __iomem *addr, u8 size);\n", 1)
for t, n in (("u8", 1), ("u16", 2), ("u32", 4)):
    sfx = {1: "b", 2: "w", 4: "l"}[n]
    old = "static inline void __raw_write%s(%s val, volatile void __iomem *addr)\n{\n" % (sfx, t)
    assert old in s, old
    s = s.replace(old, old + "\tif (unlikely(p9_iotrace_on))\n\t\tp9_iotrace(val, addr, %d);\n" % n, 1)
open(p, "w").write(s)
