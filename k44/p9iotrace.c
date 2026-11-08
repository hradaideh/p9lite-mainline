// SPDX-License-Identifier: GPL-2.0
/*
 * P9 lite, vendor 4.4 only: record MMIO writes to the display-related blocks so the working hisifb
 * power-off/power-on sequence can be replayed on mainline (k7/p9test.c).
 *   echo 1 > /sys/module/p9iotrace/parameters/on      start (clears the buffer)
 *   echo 0 > /sys/module/p9iotrace/parameters/on      stop
 *   cat /sys/kernel/debug/p9iotrace                    "usec phys size value" lines
 * Hooked from __raw_write{b,w,l} in arch/arm64/include/asm/io.h (one predictable branch when off).
 */
#include <linux/atomic.h>
#include <linux/debugfs.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/ktime.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/seq_file.h>
#include <linux/vmalloc.h>

#define P9_TRACE_N	262144
struct p9_trace_ent { u64 ns; u32 phys; u32 val; u8 size; };
static struct p9_trace_ent p9_trace[P9_TRACE_N];
static atomic_t p9_trace_idx = ATOMIC_INIT(0);
static u64 p9_trace_t0;
int p9_iotrace_on;
EXPORT_SYMBOL(p9_iotrace_on);
static int all;			/* 1: every write except the deny list (finds blocks the range list misses) */
module_param(all, int, 0644);
static const struct { u32 lo, hi; } p9_deny[] = {
	{ 0xFDF00000, 0xFDF06000 },	/* UARTs (console) */
	{ 0xE8A06000, 0xE8A07000 },	/* SP805 watchdog (fed every second) */
	{ 0xE82B0000, 0xE82B8000 },	/* GIC */
};

static const struct { u32 lo, hi; } p9_ranges[] = {
	{ 0xE8600000, 0xE8680000 },	/* DSS (GLB, DSI0, MCTL, RCH, OVL, DPP, LDI) */
	{ 0xE8A09000, 0xE8A0A000 },	/* PCTRL */
	{ 0xE8A0B000, 0xE8A20000 },	/* PL061 GPIO banks (panel reset, TE, enables) */
	{ 0xE896C000, 0xE896D000 },	/* IOMUX / IOCFG */
	{ 0xFDF09000, 0xFDF0E000 },	/* I2C controllers (backlight / bias), not the UARTs */
	{ 0xFFF0A000, 0xFFF0B000 },	/* SCTRL */
	{ 0xFFF31000, 0xFFF32000 },	/* PMCTRL */
	{ 0xFFF34000, 0xFFF35000 },	/* PMU SSI (PMIC LDOs) */
	{ 0xFFF35000, 0xFFF36000 },	/* peri CRG */
	{ 0xE896B000, 0xE896C000 },	/* IPC mailboxes (LPM3 messages) */
};

void p9_iotrace(u32 val, const volatile void __iomem *addr, u8 size)
{
	unsigned long va = (unsigned long)addr;
	u32 phys;
	int i, idx;

	if (!is_vmalloc_addr((const void *)va))
		return;
	phys = (u32)((vmalloc_to_pfn((const void *)va) << PAGE_SHIFT) | (va & ~PAGE_MASK));
	if (all) {
		for (i = 0; i < ARRAY_SIZE(p9_deny); i++)
			if (phys >= p9_deny[i].lo && phys < p9_deny[i].hi)
				return;
	} else {
		for (i = 0; i < ARRAY_SIZE(p9_ranges); i++)
			if (phys >= p9_ranges[i].lo && phys < p9_ranges[i].hi)
				break;
		if (i == ARRAY_SIZE(p9_ranges))
			return;
	}
	idx = atomic_inc_return(&p9_trace_idx) - 1;
	if (idx >= P9_TRACE_N)
		return;
	p9_trace[idx].ns = ktime_get_ns() - p9_trace_t0;
	p9_trace[idx].phys = phys;
	p9_trace[idx].val = val;
	p9_trace[idx].size = size;
}
EXPORT_SYMBOL(p9_iotrace);

static int p9_on_set(const char *s, const struct kernel_param *kp)
{
	int ret = param_set_int(s, kp);

	if (!ret && p9_iotrace_on) {
		p9_iotrace_on = 0;
		atomic_set(&p9_trace_idx, 0);
		p9_trace_t0 = ktime_get_ns();
		smp_wmb();
		p9_iotrace_on = 1;
	}
	return ret;
}
static const struct kernel_param_ops p9_on_ops = { .set = p9_on_set, .get = param_get_int };
module_param_cb(on, &p9_on_ops, &p9_iotrace_on, 0644);

static int p9_trace_show(struct seq_file *m, void *v)
{
	int i, n = min(atomic_read(&p9_trace_idx), P9_TRACE_N);

	seq_printf(m, "# %d writes%s\n", atomic_read(&p9_trace_idx),
		   atomic_read(&p9_trace_idx) > P9_TRACE_N ? " (buffer full, truncated)" : "");
	for (i = 0; i < n; i++)
		seq_printf(m, "%llu %08x %u %08x\n", p9_trace[i].ns / 1000, p9_trace[i].phys,
			   p9_trace[i].size, p9_trace[i].val);
	return 0;
}
static int p9_trace_open(struct inode *inode, struct file *file)
{
	return single_open_size(file, p9_trace_show, NULL, P9_TRACE_N * 40);
}
static const struct file_operations p9_trace_fops = {
	.open = p9_trace_open, .read = seq_read, .llseek = seq_lseek, .release = single_release,
};
static int __init p9_iotrace_init(void)
{
	debugfs_create_file("p9iotrace", 0400, NULL, NULL, &p9_trace_fops);
	return 0;
}
late_initcall(p9_iotrace_init);
