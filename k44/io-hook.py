#!/usr/bin/env python3
"""Hook __raw_write{b,w,l} in the vendor 4.4 arch/arm64/include/asm/io.h for p9iotrace. Idempotent."""
import sys
p = sys.argv[1] + "/arch/arm64/include/asm/io.h"
s = open(p).read()
if "p9_iotrace(val" in s and "p9_iotrace_rd" in s:
    sys.exit(0)
if "extern int p9_iotrace_on" not in s:
    s = s.replace("#include <xen/xen.h>\n", "#include <xen/xen.h>\n\nextern int p9_iotrace_on;\n"
                  "void p9_iotrace(u32 val, const volatile void __iomem *addr, u8 size);\n", 1)
for t, n in (("u8", 1), ("u16", 2), ("u32", 4)):
    sfx = {1: "b", 2: "w", 4: "l"}[n]
    old = "static inline void __raw_write%s(%s val, volatile void __iomem *addr)\n{\n" % (sfx, t)
    assert old in s, old
    if "p9_iotrace(val, addr, %d)" % n in s:
        continue
    s = s.replace(old, old + "\tif (unlikely(p9_iotrace_on))\n\t\tp9_iotrace(val, addr, %d);\n" % n, 1)
if "p9_iotrace_rd" not in s:
    s = s.replace("void p9_iotrace(u32 val, const volatile void __iomem *addr, u8 size);\n",
                  "void p9_iotrace(u32 val, const volatile void __iomem *addr, u8 size);\n"
                  "void p9_iotrace_rd(u32 val, const volatile void __iomem *addr, u8 size);\n", 1)
    old = """static inline u32 __raw_readl(const volatile void __iomem *addr)
{
	u32 val;
	asm volatile(ALTERNATIVE("ldr %w0, [%1]",
				 "ldar %w0, [%1]",
				 ARM64_WORKAROUND_DEVICE_LOAD_ACQUIRE)
		     : "=r" (val) : "r" (addr));
	return val;
}"""
    assert old in s, "readl pattern"
    s = s.replace(old, old.replace("\treturn val;", "\tif (unlikely(p9_iotrace_on))\n\t\tp9_iotrace_rd(val, addr, 4);\n\treturn val;"))
open(p, "w").write(s)
