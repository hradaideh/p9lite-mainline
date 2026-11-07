// SPDX-License-Identifier: GPL-2.0
/*
 * P9 Lite (HiSilicon hi6250) bring-up helper for mainline boot tests.
 *
 *  - keeps the SP805 watchdog that the Huawei bootloader enables fed
 *    (otherwise the board resets after ~60 s and the boot-fail monitor
 *    eventually sends the phone to eRecovery);
 *  - after p9test.reboot_delay seconds prints a short report (CPUs, memory,
 *    bound platform/amba devices) so it lands in pstore;
 *  - on any restart or panic writes the Huawei reboot reason BOOTLOADER into
 *    the PMIC reset register and asks LPM3 to reset the board, exactly like the
 *    vendor kernel's hisi_pm_system_reset(), so the phone stops in fastboot with
 *    RAM (and therefore pstore) preserved.
 *
 * Addresses come from the vendor 4.4 tree (drivers/hisi/mntn) and the phone's DT.
 */
#include <linux/amba/bus.h>
#include <linux/cpumask.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/hrtimer.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/ktime.h>
#include <linux/mm.h>
#include <linux/moduleparam.h>
#include <linux/notifier.h>
#include <linux/panic_notifier.h>
#include <linux/of.h>
#include <linux/slab.h>
#include <linux/kmsg_dump.h>
#include <linux/of_platform.h>
#include <linux/mmc/host.h>
#include "../mmc/host/dw_mmc.h"
#include <linux/debugfs.h>
#include <linux/of_platform.h>
#include <linux/pinctrl/consumer.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/clk-provider.h>
#include <linux/string.h>
#include <linux/sysfs.h>
#include <linux/vmalloc.h>
#include <linux/platform_device.h>
#include <linux/printk.h>
#include <linux/reboot.h>
#include <linux/workqueue.h>

#define P9_WDT_BASE		0xE8A06000UL	/* arm,sp805 watchdog0 */
#define SP805_INTCLR		0x0C
#define SP805_LOCK		0xC00
#define SP805_UNLOCK_KEY	0x1ACCE551
#define P9_PMU_RESET_REG	0xFFF3462CUL	/* PMU SSI0 0xFFF34000 + (0x18B << 2) */
#define P9_NMI_LPM3_REG		0xFFF0A510UL	/* NMI_NOTIFY_LPM3_ADDR */
#define P9_REASON_BOOTLOADER	0x01
#define P9_REASON_COLDBOOT	0x10	/* vendor hisi_pm_system_reset() for a plain reboot */
#define P9_PMU_SSI_BASE		0xFFF34000UL	/* Hi6555 PMIC registers, one byte per 32-bit word */
#define P9_COUL_CURRENT		0x1F2	/* Hi6555 coulomb counter, s16 little endian */
#define P9_COUL_V_OUT		0x1F4
#define P9_RST_FLAG_MASK	0xFF

static unsigned int reboot_delay = 20;
module_param(reboot_delay, uint, 0444);
/* watchdog is fed unconditionally only for feed_grace seconds; after that only once
 * userspace has set /sys/module/p9test/parameters/keepalive=1. A boot that stalls
 * before /init therefore gets a watchdog (warm) reset -> fastboot, log kept in RAM. */
static unsigned int feed_grace = 90;
module_param(feed_grace, uint, 0444);
static bool keepalive;
module_param(keepalive, bool, 0644);
/* bisect switches (kernel cmdline p9test.<name>=0/1) */
static bool save_periodic = true;
module_param(save_periodic, bool, 0444);
static bool early_reason = true;
module_param(early_reason, bool, 0444);
/* p9test.prod=1: production use. Restarts follow the command (reboot -> COLDBOOT, i.e. boot this kernel
 * again; "reboot bootloader" -> fastboot), no report/auto-reboot, watchdog fed for as long as the kernel runs,
 * no fastboot preset at boot. prod=0 keeps the test semantics: every restart stops in fastboot. */
static bool prod;
module_param(prod, bool, 0444);
/* Boot guard (prod): until userspace writes boot_ok=1, every reset (panic, watchdog, reboot) goes to fastboot
 * and boot_deadline seconds without boot_ok force one. Huawei's bootloader counts resets that happen before
 * the boot keypoint reaches 250 (STAGE_ANDROID_BOOT_SUCCESS) as boot failures and, after a few, boots eRecovery
 * (boot-fail mode); fastboot-reason resets have never tripped it. boot_ok=1 writes keypoint 250 like stock. */
#define P9_PMU_KEYPOINT_REG	0xFFF34630UL	/* PMU SSI0 + (PMIC_HRST_REG1 0x18C << 2), hisi_bootup_keypoint.c */
#define P9_STAGE_BOOT_SUCCESS	250
static unsigned int boot_deadline = 600;
module_param(boot_deadline, uint, 0444);
static bool boot_ok, panicked;
static struct delayed_work deadline_work;
static int p9_boot_ok_set(const char *val, const struct kernel_param *kp);
static const struct kernel_param_ops p9_boot_ok_ops = { .set = p9_boot_ok_set, .get = param_get_bool };
module_param_cb(boot_ok, &p9_boot_ok_ops, &boot_ok, 0644);
static bool sdio_prep = true;
module_param(sdio_prep, bool, 0444);
static bool sdio_power = true;		/* 0: leave the Hi1102 as r16/bootloader left it */
module_param(sdio_power, bool, 0644);
/* arm the SP805 ourselves (the bootloader-enabled one does not reset the board) */
static unsigned int wdt_timeout = 20;
module_param(wdt_timeout, uint, 0444);
/* echo 1 > /sys/module/p9test/parameters/restart_now: escape a hung test kernel to fastboot.
 * emergency_restart() skips device_shutdown(), which blocks forever on a device lock held by a
 * stuck driver task. Never escape via a watchdog reset: that trips Huawei boot-fail mode. */
static int p9_restart_now(const char *val, const struct kernel_param *kp)
{
	pr_emerg("p9test: restart_now\n");
	emergency_restart();
	return 0;
}
static const struct kernel_param_ops p9_restart_now_ops = { .set = p9_restart_now };
module_param_cb(restart_now, &p9_restart_now_ops, NULL, 0200);

static void __iomem *wdt, *pmu_rst, *nmi, *pmu_ssi;

/* cat /sys/module/p9test/parameters/battery -> "<uV> <uA> raw_v=.. raw_i=.."
 * Hi6555 gauge, vendor hi6555v100_coul conversions with default calibration (a=1e6, b=0) and the
 * 10 mOhm sense resistor. Vendor: high bit of the current = into the battery. No mainline driver. */
static u16 p9_pmu_read16(unsigned int reg)
{
	return (readl(pmu_ssi + (reg << 2)) & 0xff) | (readl(pmu_ssi + ((reg + 1) << 2)) & 0xff) << 8;
}
static int p9_battery_get(char *buf, const struct kernel_param *kp)
{
	u16 v, i;

	if (!pmu_ssi)
		return sysfs_emit(buf, "unavailable\n");
	v = p9_pmu_read16(P9_COUL_V_OUT);
	i = p9_pmu_read16(P9_COUL_CURRENT);
	return sysfs_emit(buf, "%lld %lld raw_v=0x%04x raw_i=0x%04x\n",
			  (long long)(v & 0x7fff) * 2400000 / 10661,
			  (long long)(s16)i * 5000000 / 10661, v, i);
}
static const struct kernel_param_ops p9_battery_ops = { .get = p9_battery_get };
module_param_cb(battery, &p9_battery_ops, NULL, 0444);
static struct hrtimer pet_timer;
static struct delayed_work report_work;

static void p9_wdt_pet(void)
{
	if (!wdt)
		return;
	writel(SP805_UNLOCK_KEY, wdt + SP805_LOCK);
	writel(1, wdt + SP805_INTCLR);	/* clears irq and reloads the counter */
	writel(0, wdt + SP805_LOCK);
}

/* Crash marker in the last page of the vendor ramoops region (pmsg zone end, unused by pmOS), which survives
 * the warm reset of a watchdog/tsensor reset. Those resets bypass every kernel hook and the firmware overwrites
 * the reset reason, so the next boot detects them here instead: a marker still in BOOTING means the previous
 * boot died before boot_ok -> keep its log untouched and restart straight to fastboot. */
#define P9_MARK_PHYS	0x348FF000UL
#define P9_MARK_MAGIC	0x54423950	/* "P9BT" */
enum { P9_MARK_CLEAN = 1, P9_MARK_BOOTING, P9_MARK_RUNNING };
static u32 *mark;
static bool keep_log;	/* this boot only reports a previous crash: never overwrite its saved log */
static bool starve;	/* test only: stop petting the SP805 to reproduce a watchdog reset */
static bool early_success = true;
module_param(early_success, bool, 0444);

/* p9early on the cmdline: the same keypoint + crash-marker logic, run from parse_early_param (setup_arch),
 * long before p9test's core_initcall. Some boots died earlier than core_initcall (bootfail_info:
 * KERNEL_AP_WDT at BL2_STAGE_END), where nothing else of p9test can act. No linear map exists yet,
 * so the RAM page is mapped with early_ioremap (uncached: the marker must reach DRAM before a reset). */
static bool early_hook_ran;
static int __init p9_early_hook(char *arg)
{
	void __iomem *pmu = early_ioremap(P9_PMU_SSI_BASE, PAGE_SIZE);
	void __iomem *m = early_ioremap(P9_MARK_PHYS, PAGE_SIZE);
	void __iomem *nmi_e;
	u32 v;

	if (!pmu || !m)
		return 0;
	writel(P9_STAGE_BOOT_SUCCESS, pmu + (P9_PMU_KEYPOINT_REG - P9_PMU_SSI_BASE));
	if (readl(m + 0xFF0) == P9_MARK_MAGIC && readl(m + 0xFF4) == P9_MARK_BOOTING) {
		/* previous boot died before boot_ok: straight to fastboot, its saved log untouched */
		writel(P9_MARK_CLEAN, m + 0xFF4);
		v = readl(pmu + (P9_PMU_RESET_REG - P9_PMU_SSI_BASE));
		writel((v & ~P9_RST_FLAG_MASK) | P9_REASON_BOOTLOADER, pmu + (P9_PMU_RESET_REG - P9_PMU_SSI_BASE));
		nmi_e = early_ioremap(P9_NMI_LPM3_REG & PAGE_MASK, PAGE_SIZE);
		if (nmi_e) {
			nmi_e += P9_NMI_LPM3_REG & ~PAGE_MASK;
			v = readl(nmi_e);
			writel(v | BIT(2), nmi_e);
			writel(v & ~BIT(2), nmi_e);
		}
		for (;;)
			cpu_relax();
	}
	writel(P9_MARK_MAGIC, m + 0xFF0);
	writel(P9_MARK_BOOTING, m + 0xFF4);
	early_iounmap(m, PAGE_SIZE);
	early_iounmap(pmu, PAGE_SIZE);
	early_hook_ran = true;
	return 0;
}
early_param("p9early", p9_early_hook);

static void p9_mark_set(u32 state)
{
	if (!mark)
		return;
	WRITE_ONCE(mark[1], state);
	WRITE_ONCE(mark[0], P9_MARK_MAGIC);
	wmb();
}

static int p9_starve_set(const char *val, const struct kernel_param *kp)
{
	pr_emerg("p9test: starve_wdt: no more SP805 petting, watchdog reset in ~20 s\n");
	starve = true;
	return 0;
}
static const struct kernel_param_ops p9_starve_ops = { .set = p9_starve_set };
module_param_cb(starve_wdt, &p9_starve_ops, NULL, 0200);

static enum hrtimer_restart p9_pet_fn(struct hrtimer *t)
{
	if (starve) {
		;
	} else if (keepalive || ktime_get_boottime_seconds() < feed_grace) {
		p9_wdt_pet();
	} else {
		/* /init never reported in: force the restart ourselves (log saved, -> fastboot) */
		pr_emerg("p9test: no keepalive from userspace after %us, emergency restart\n",
			 feed_grace);
		emergency_restart();
	}
	hrtimer_forward_now(t, ms_to_ktime(1000));
	return HRTIMER_RESTART;
}

/*
 * Write the kernel log straight into the console zone of the vendor ramoops
 * region, in the vendor 4.4 persistent_ram_buffer format, so the vendor kernel
 * shows it as /sys/fs/pstore/console-ramoops-0 on the next boot.
 *   region 0x34800000 (1 MiB): 3 x 128K dump records, then console 512K @ +0x60000
 */
#define P9_CON_PHYS	0x34860000UL
#define P9_CON_SIZE	0x80000UL
#define P9_RAM_SIG	0x43474244	/* "DBGC" */
static u8 *con_zone;
static char *con_buf;

/* same approach as fs/pstore/ram_core.c: vmap RAM pages write-combined, ioremap otherwise */
static u8 *p9_map_wc(phys_addr_t start, size_t size)
{
	unsigned int i, n = size >> PAGE_SHIFT;
	struct page **pages;
	void *va;

	if (!pfn_valid(PHYS_PFN(start))) {
		pr_info("p9test: console zone not in linear map, using ioremap_wc\n");
		return (u8 __force *)ioremap_wc(start, size);
	}
	pages = kmalloc_array(n, sizeof(*pages), GFP_KERNEL);
	if (!pages)
		return NULL;
	for (i = 0; i < n; i++)
		pages[i] = pfn_to_page(PHYS_PFN(start) + i);
	va = vmap(pages, n, VM_MAP, pgprot_writecombine(PAGE_KERNEL));
	kfree(pages);
	pr_info("p9test: console zone is RAM, vmap wc -> %p\n", va);
	return va;
}

static void p9_save_log(void)
{
	struct kmsg_dump_iter iter;
	size_t len = 0, cap = P9_CON_SIZE - 12;
	u32 *hdr = (u32 *)con_zone;

	if (!con_zone || !con_buf || keep_log)
		return;
	kmsg_dump_rewind(&iter);
	kmsg_dump_get_buffer(&iter, false, con_buf, cap, &len);
	memcpy(con_zone + 12, con_buf, len);
	WRITE_ONCE(hdr[1], (u32)len);	/* start: next write position */
	WRITE_ONCE(hdr[2], (u32)len);	/* size: bytes valid */
	wmb();
	WRITE_ONCE(hdr[0], P9_RAM_SIG);	/* signature last */
	wmb();
}

static int p9_restart(struct notifier_block *nb, unsigned long mode, void *cmd)
{
	u32 v, reason = P9_REASON_BOOTLOADER;

	if (prod && boot_ok && !panicked && !(cmd && !strcmp(cmd, "bootloader")))
		reason = P9_REASON_COLDBOOT;
	p9_mark_set(P9_MARK_CLEAN);
	pr_emerg("p9test: restart (%s) -> %s\n", cmd ? (char *)cmd : "-",
		 reason == P9_REASON_BOOTLOADER ? "fastboot" : "normal boot");
	p9_save_log();
	if (pmu_rst) {
		v = readl(pmu_rst);
		v = (v & ~P9_RST_FLAG_MASK) | reason;
		writel(v, pmu_rst);
	}
	if (nmi) {
		v = readl(nmi);
		writel(v | BIT(2), nmi);
		writel(v & ~BIT(2), nmi);
	}
	mdelay(3000);
	pr_emerg("p9test: LPM3 reset did not happen, falling back\n");
	return NOTIFY_DONE;
}

static struct notifier_block p9_restart_nb = {
	.notifier_call = p9_restart,
	.priority = 255,
};

static int p9_panic(struct notifier_block *nb, unsigned long ev, void *msg)
{
	panicked = true;	/* the restart that follows goes to fastboot, never a crash loop */
	p9_save_log();
	return NOTIFY_DONE;
}

static struct notifier_block p9_panic_nb = {
	.notifier_call = p9_panic,
	.priority = INT_MAX,
};

static void p9_set_reason(u32 reason)
{
	if (pmu_rst)
		writel((readl(pmu_rst) & ~P9_RST_FLAG_MASK) | reason, pmu_rst);
}

static int p9_boot_ok_set(const char *val, const struct kernel_param *kp)
{
	void __iomem *kp_reg;
	int ret = param_set_bool(val, kp);

	if (ret || !boot_ok)
		return ret;
	cancel_delayed_work(&deadline_work);
	kp_reg = ioremap(P9_PMU_KEYPOINT_REG & PAGE_MASK, PAGE_SIZE);
	if (kp_reg) {
		writel(P9_STAGE_BOOT_SUCCESS, kp_reg + (P9_PMU_KEYPOINT_REG & ~PAGE_MASK));
		iounmap(kp_reg);
	}
	p9_mark_set(P9_MARK_RUNNING);
	if (prod)
		p9_set_reason(P9_REASON_COLDBOOT);	/* a later unplanned reset boots normally again */
	pr_info("p9test: boot_ok: keypoint %u, reboots now boot normally\n", P9_STAGE_BOOT_SUCCESS);
	return 0;
}

/* reboot/poweroff: device_shutdown() can block forever behind a stuck driver while the watchdog is still fed.
 * Once a shutdown starts, force the restart after 30 s (prod + boot_ok -> normal boot, else fastboot). */
static struct hrtimer shutdown_timer;
static enum hrtimer_restart p9_shutdown_fn(struct hrtimer *t)
{
	pr_emerg("p9test: shutdown stuck for 30 s, forcing restart\n");
	emergency_restart();
	return HRTIMER_NORESTART;
}

static int p9_reboot_notify(struct notifier_block *nb, unsigned long ev, void *cmd)
{
	p9_mark_set(P9_MARK_CLEAN);
	hrtimer_start(&shutdown_timer, ms_to_ktime(30000), HRTIMER_MODE_REL);
	return NOTIFY_DONE;
}

static struct notifier_block p9_reboot_nb = { .notifier_call = p9_reboot_notify };

static void p9_deadline_fn(struct work_struct *w)
{
	pr_emerg("p9test: no boot_ok from userspace after %us, restarting to fastboot\n", boot_deadline);
	emergency_restart();
}

static int p9_print_dev(struct device *dev, void *data)
{
	pr_info("p9test: %s dev %s driver=%s\n", (const char *)data, dev_name(dev),
		dev->driver ? dev->driver->name : "-");
	return 0;
}

static void p9_report(struct work_struct *w)
{
	pr_info("p9test: ===== REPORT uptime=%llus cpus_online=%u/%u totalram=%luMB =====\n",
		ktime_get_boottime_seconds(), num_online_cpus(), num_possible_cpus(),
		totalram_pages() >> (20 - PAGE_SHIFT));
	bus_for_each_dev(&platform_bus_type, NULL, "platform", p9_print_dev);
#ifdef CONFIG_ARM_AMBA
	bus_for_each_dev(&amba_bustype, NULL, "amba", p9_print_dev);
#endif
	pr_info("p9test: ===== END REPORT, rebooting to bootloader =====\n");
	emergency_restart();	/* same p9_restart path, without device_shutdown() */
}

/*
 * The vendor DT stores ramoops sizes as 64-bit (two cells, #size-cells = 2),
 * mainline reads them as u32 and gets 0 -> ramoops refuses to register.
 * Rewrite them as single-cell values in the live tree before ramoops probes.
 */
static void __init p9_fix_ramoops_dt(void)
{
	static const char * const names[] = {
		"record-size", "console-size", "ftrace-size", "pmsg-size", "ecc-size",
	};
	struct device_node *np = of_find_compatible_node(NULL, NULL, "ramoops");
	int i;

	if (!np) {
		pr_info("p9test: no ramoops node\n");
		return;
	}
	for (i = 0; i < ARRAY_SIZE(names); i++) {
		struct property *old = of_find_property(np, names[i], NULL), *p;
		u64 v64;
		__be32 *val;

		if (!old || old->length != 8 || of_property_read_u64(np, names[i], &v64))
			continue;
		p = kzalloc(sizeof(*p) + sizeof(*val), GFP_KERNEL);
		if (!p)
			continue;
		val = (__be32 *)(p + 1);
		*val = cpu_to_be32((u32)v64);
		p->name = kstrdup(names[i], GFP_KERNEL);
		p->value = val;
		p->length = sizeof(*val);
		of_update_property(np, p);
		pr_info("p9test: ramoops %s -> 0x%llx (u32)\n", names[i], v64);
	}
	of_node_put(np);
}

/*
 * eMMC shortcut: the eMMC is an Arasan SDHCI at 0xFF390000 (vendor compatible
 * "arasan,sdhci"). Mainline sdhci-of-arasan needs clk_xin/clk_ahb from a clock
 * driver hi6250 does not have, and a vmmc regulator from the vendor PMIC driver.
 * The bootloader already powers the eMMC, so:
 *   - switch the two clock gates on in the peri CRG (write-1-to-set registers),
 *   - register fixed-rate stand-in clocks (rates read from the vendor kernel) as
 *     providers for the two vendor gate nodes used only by the eMMC,
 *   - drop vmmc-supply and use the mainline "arasan,sdhci-8.9a" compatible.
 */
#define P9_PERI_CRG		0xFFF35000UL
#include <linux/delay.h>
static void p9_set_prop_str(struct device_node *np, const char *name, const char *val)
{
	struct property *p = kzalloc(sizeof(*p), GFP_KERNEL);

	if (!p)
		return;
	p->name = kstrdup(name, GFP_KERNEL);
	p->value = kstrdup(val, GFP_KERNEL);
	p->length = strlen(val) + 1;
	of_update_property(np, p);
}

static void p9_set_prop_u32s(struct device_node *np, const char *name,
				    const u32 *vals, int n)
{
	struct property *p = kzalloc(sizeof(*p) + n * sizeof(__be32), GFP_KERNEL);
	__be32 *v;
	int i;

	if (!p)
		return;
	v = (__be32 *)(p + 1);
	for (i = 0; i < n; i++)
		v[i] = cpu_to_be32(vals[i]);
	p->name = kstrdup(name, GFP_KERNEL);
	p->value = v;
	p->length = n * sizeof(__be32);
	of_update_property(np, p);
}

static void __init p9_fixed_clk_for(const char *outname, unsigned long rate)
{
	struct device_node *np;
	struct clk_hw *hw;
	char name[32];

	for_each_node_with_property(np, "clock-output-names") {
		const char *n;

		if (of_property_read_string(np, "clock-output-names", &n) || strcmp(n, outname))
			continue;
		snprintf(name, sizeof(name), "p9_%s", outname);
		hw = clk_hw_register_fixed_rate(NULL, name, NULL, 0, rate);
		if (IS_ERR(hw)) {
			pr_err("p9test: fixed clk %s failed\n", name);
		} else {
			of_clk_add_hw_provider(np, of_clk_hw_simple_get, hw);
			pr_info("p9test: stand-in clock %s = %lu Hz for node %pOF\n", name, rate, np);
		}
		of_node_put(np);
		return;
	}
	pr_err("p9test: clock node %s not found\n", outname);
}

static void __init p9_fix_emmc(void)
{
	struct device_node *np = of_find_compatible_node(NULL, NULL, "arasan,sdhci");
	void __iomem *crg = ioremap(P9_PERI_CRG, 0x1000);
	struct property *pp;

	if (crg) {
		writel(BIT(15), crg + 0x40);	/* PEREN4: clk_emmc0  */
		writel(BIT(13), crg + 0x00);	/* PEREN0: hclk_emmc0 */
		pr_info("p9test: eMMC gates on, PERSTAT4=0x%08x PERSTAT0=0x%08x\n",
			readl(crg + 0x48), readl(crg + 0x08));
		iounmap(crg);
	}
	p9_fixed_clk_for("clk_emmc0", 200000000);
	p9_fixed_clk_for("hclk_emmc0", 120000000);
	if (!np) {
		pr_err("p9test: no arasan,sdhci node\n");
		return;
	}
	pp = of_find_property(np, "vmmc-supply", NULL);
	if (pp)
		of_remove_property(np, pp);
	p9_set_prop_str(np, "compatible", "arasan,sdhci-8.9a");
	pr_info("p9test: eMMC node %pOF -> arasan,sdhci-8.9a, vmmc-supply dropped\n", np);
	of_node_put(np);
}

/*
 * i2c4 (0xFDF0D000): fsa9682@26 USB switch, smartpa@31, hi6522 charger/LCD-power PMIC @6B.
 * Mainline i2c-designware drives it once the node uses the snps compatible and has a clock:
 *   - enable clk_i2c4 (PEREN2 bit 27); the bootloader already took it out of reset,
 *   - drop the vendor clocks (hi6250 CRG provider does not exist) and register a fixed
 *     120 MHz clock (DT clock-rate) for the device through clkdev,
 *   - 100 kHz (driver default would be 400 kHz).
 * The node's pinctrl-0 (GPIO037/038 -> func 1) is applied by the driver core; without it
 * every address NACKs.
 */
#include <linux/clkdev.h>
static void __init p9_fix_i2c4(void)
{
	struct device_node *np = of_find_node_by_path("/amba/i2c@FDF0D000");
	void __iomem *crg = ioremap(P9_PERI_CRG, 0x1000);
	struct property *pp;
	struct clk_hw *hw;
	static const u32 freq = 100000;

	if (crg) {
		writel(BIT(27), crg + 0x20);	/* PEREN2: clk_i2c4 */
		pr_info("p9test: i2c4 gate on, PERSTAT2=0x%08x\n", readl(crg + 0x2c));
		iounmap(crg);
	}
	if (!np) {
		pr_err("p9test: no i2c@FDF0D000 node\n");
		return;
	}
	pp = of_find_property(np, "clocks", NULL);
	if (pp)
		of_remove_property(np, pp);
	pp = of_find_property(np, "clock-names", NULL);
	if (pp)
		of_remove_property(np, pp);
	hw = clk_hw_register_fixed_rate(NULL, "p9_clk_i2c4", NULL, 0, 120000000);
	if (!IS_ERR(hw))
		clk_hw_register_clkdev(hw, NULL, "fdf0d000.i2c");
	p9_set_prop_u32s(np, "clock-frequency", &freq, 1);
	p9_set_prop_str(np, "compatible", "snps,designware-i2c");
	pr_info("p9test: i2c4 node %pOF -> snps,designware-i2c, 120 MHz stand-in clock, 100 kHz\n", np);
	of_node_put(np);
}

/*
 * USB device mode: replay the vendor PHY bring-up (drivers/usb/susb/dwc_otg_hi6250.c,
 * init_usb_otg_phy_hi6250 in device mode) and hand the Synopsys DWC OTG core at
 * 0xFF100000 to mainline dwc2 using the HiKey (hi6220) parameter set.
 */
#define P9_PCTRL		0xE8A09000UL
#define P9_USB_AHBIF		0xFF200000UL
#define P9_PMU_ABB_GATE		(0xFFF34000UL + (0x10f << 2))	/* clk_abb_192 PMU gate, bit 0 */
#define P9_USB_EYE_DEVICE	0x06ac66db			/* DT eye_diagram_param */

static void __init p9_usb_phy_init(void)
{
	void __iomem *crg = ioremap(P9_PERI_CRG, 0x1000);
	void __iomem *pctrl = ioremap(P9_PCTRL, 0x1000);
	void __iomem *ahb = ioremap(P9_USB_AHBIF, 0x1000);
	void __iomem *pmu = ioremap(P9_PMU_ABB_GATE & PAGE_MASK, PAGE_SIZE);
	u32 v;

	if (!crg || !pctrl || !ahb || !pmu) {
		pr_err("p9test: usb ioremap failed\n");
		goto out;
	}
	pmu += P9_PMU_ABB_GATE & ~PAGE_MASK;
	/* ABB 19.2 MHz reference for the PHY */
	v = readl(pctrl + 0x64);
	v = (v & ~(7 << 24)) | (5 << 24);
	writel(v, pctrl + 0x64);
	writel(readl(pmu) | BIT(0), pmu);
	/* hclk_usb2otg on, ahbif out of reset (ADP, 32K, MUX, AHBIF) */
	writel(BIT(1), crg + 0x40);
	writel(BIT(27) | BIT(14) | BIT(10) | BIT(11), crg + 0x94);
	/* ctrl0: id from PHY iddig, ACA enable from register = 0 */
	v = readl(ahb + 0x00);
	v = (v & ~(3 << 4)) | (1 << 4);
	v |= BIT(2);
	v &= ~BIT(3);
	writel(v, ahb + 0x00);
	writel(P9_USB_EYE_DEVICE, ahb + 0x0c);
	/* PHY POR, PHY clock domain, controller hclk domain out of reset */
	writel(BIT(13), crg + 0x94);
	udelay(50);
	writel(BIT(12), crg + 0x94);
	udelay(100);
	writel(BIT(9), crg + 0x94);
	/* vbusvalid from register, asserted */
	writel(readl(ahb + 0x08) | BIT(2) | BIT(3), ahb + 0x08);
	mdelay(1);
	pr_info("p9test: usb phy up: CLKSTAT4=0x%08x RSTSTAT4=0x%08x ctrl0=0x%08x ctrl2=0x%08x\n",
		readl(crg + 0x4c), readl(crg + 0x98), readl(ahb), readl(ahb + 0x08));
out:
	if (crg) iounmap(crg);
	if (pctrl) iounmap(pctrl);
	if (ahb) iounmap(ahb);
}

static void __init p9_fix_usb_dt(void)
{
	struct device_node *np = of_find_compatible_node(NULL, NULL, "hisilicon,hi6250-usb-otg");

	if (!np) {
		pr_err("p9test: no usb otg node\n");
		return;
	}
	/* fw_devlink would hold the device back forever on suppliers that have no driver */
	{
		static const char * const drop[] = { "clocks", "clock-names", "otgdebugsubsys-supply" };
		int i;

		for (i = 0; i < ARRAY_SIZE(drop); i++) {
			struct property *pp = of_find_property(np, drop[i], NULL);

			if (pp)
				of_remove_property(np, pp);
		}
	}
	/* gadget FIFO layout (same as the HiKey hi6220 dwc2 node); core has 3968 SPRAM entries */
	{
		/* all 15 TX FIFOs must be given (zeros are "invalid" and get oversized defaults) */
		static const u32 txf[] = { 128, 128, 128, 128, 128, 128, 128, 128,
					   128, 128, 128, 128, 128, 128, 128 };
		p9_set_prop_u32s(np, "g-rx-fifo-size", (const u32[]){ 512 }, 1);
		p9_set_prop_u32s(np, "g-np-tx-fifo-size", (const u32[]){ 128 }, 1);
		p9_set_prop_u32s(np, "g-tx-fifo-size", txf, ARRAY_SIZE(txf));
	}
	p9_set_prop_str(np, "compatible", "hisilicon,hi6220-usb");
	p9_set_prop_str(np, "dr_mode", "peripheral");
	pr_info("p9test: usb node %pOF -> hisilicon,hi6220-usb (dwc2), dr_mode=peripheral\n", np);
	of_node_put(np);
}

/*
 * Wi-Fi step 1: SDIO host dwmmc2 (0xFF37D000) on mainline dw_mmc-k3 and power the
 * Hi1102 so it can enumerate. Sequence from vendor platform/board/board.c:
 * 32 kHz PMU clock on, XLDO gpio = 1, power_on gpio low 10 ms -> high, wait 30 ms.
 */
#define P9_PMU_CLK32KB		(0xFFF34000UL + (0x121 << 2))	/* clk_pmu32kb = bit 1 */
#define P9_GPIO_PWRON_BASE	0xE8A0F000UL			/* hi1102,gpio_power_on pin 3 */
#define P9_GPIO_XLDO_BASE	0xE8A16000UL			/* hi1102,gpio_xldo_pinmux pin 3 */
#define PL061_DIR		0x400

static void p9_pl061_set(void __iomem *base, int pin, int val)
{
	writel(readl(base + PL061_DIR) | BIT(pin), base + PL061_DIR);
	writel(val ? BIT(pin) : 0, base + (BIT(pin) << 2));
}

/* boot time: stand-in clocks + DT rewrite, node left DISABLED (probe happens on demand) */
static void __init p9_sdio_dt_prepare(void)
{
	struct device_node *np;

	p9_fixed_clk_for("clk_sdio0", 3200000);	/* clk_factor_mmc0: 19.2 MHz / 6 */
	p9_fixed_clk_for("hclk_sdio0", 120000000);
	np = of_find_node_by_path("/dwmmc2@ff37d000");
	if (!np) {
		pr_err("p9test: no dwmmc2 node\n");
		return;
	}
	p9_set_prop_str(np, "compatible", "hisilicon,hi3660-dw-mshc");	/* writes the vendor GPIO reg: CLK_ENABLE + div */
	p9_set_prop_str(np, "status", "disabled");
	p9_set_prop_u32s(np, "bus-width", (const u32[]){ 4 }, 1);
	p9_set_prop_u32s(np, "max-frequency", (const u32[]){ 3200000 }, 1);
	{
		static const char * const flags[] = { "non-removable", "cap-sdio-irq",
						      "keep-power-in-suspend", "p9,ocr-1v8" };
		int i;

		for (i = 0; i < ARRAY_SIZE(flags); i++) {
			struct property *p = kzalloc(sizeof(*p), GFP_KERNEL);

			if (!p)
				continue;
			p->name = kstrdup(flags[i], GFP_KERNEL);
			of_update_property(np, p);
		}
	}
	pr_info("p9test: sdio node prepared (disabled until 'echo 1 > /sys/kernel/debug/p9test/sdio')\n");
	of_node_put(np);
}

/* run time: clocks, reset release, Hi1102 power, then create + probe the SDIO host */
/*
 * microSD slot (dwmmc1 @ 0xFF37F000) for mainline dw_mmc-k3 (hi3660 flavour, as for SDIO).
 * The bootloader leaves card power (PMIC LDO16 vmmc, LDO9 vqmmc, both 2.95 V), clk_sd/hclk_sd and
 * the resets in a usable state, but not the clock source: clk_sd_muxsys points at the PLL path
 * (ppll3 / 4), whose "AP" branch needs an LPM3 IPC request that mainline never sends.
 * ponytail: run from clk_factor_mmc0 = 19.2 MHz / 6 = 3.2 MHz (always on; the vendor also uses it for
 * the 400 kHz LEGACY mode). dw_mmc-k3 divides by 8, so the card clock is 400 kHz (~200 KB/s);
 * enable a PLL branch via LPM3 for 25/50 MHz. No regulator/GPIO drivers bind here, so vmmc/vqmmc and
 * cd-gpio are dropped and the core polls for the card (broken-cd).
 * Node left disabled at boot; probe on demand: echo 1 > /sys/kernel/debug/p9test/sd
 */
#define P9_SD_NODE	"/dwmmc1@FF37F000"
static void __init p9_sd_dt_prepare(void)
{
	static const char * const drop[] = { "vmmc-supply", "vqmmc-supply", "cd-gpio", "supports-highspeed" };
	static const char * const flags[] = { "broken-cd", "disable-wp", "cap-sd-highspeed" };
	struct device_node *np = of_find_node_by_path(P9_SD_NODE);
	struct property *pp;
	int i;

	if (!np) {
		pr_err("p9test: no %s node\n", P9_SD_NODE);
		return;
	}
	p9_fixed_clk_for("clk_sd", 3200000);
	p9_fixed_clk_for("hclk_sd", 120000000);
	for (i = 0; i < ARRAY_SIZE(drop); i++) {
		pp = of_find_property(np, drop[i], NULL);
		if (pp)
			of_remove_property(np, pp);
	}
	p9_set_prop_str(np, "compatible", "hisilicon,hi3660-dw-mshc");
	p9_set_prop_str(np, "status", "disabled");
	p9_set_prop_u32s(np, "bus-width", (const u32[]){ 4 }, 1);
	p9_set_prop_u32s(np, "max-frequency", (const u32[]){ 3200000 }, 1);
	for (i = 0; i < ARRAY_SIZE(flags); i++) {
		struct property *p = kzalloc(sizeof(*p), GFP_KERNEL);

		if (!p)
			continue;
		p->name = kstrdup(flags[i], GFP_KERNEL);
		of_update_property(np, p);
	}
	pr_info("p9test: sd node prepared (disabled until 'echo 1 > /sys/kernel/debug/p9test/sd')\n");
	of_node_put(np);
}

static int p9_sd_bringup(void)
{
	void __iomem *crg = ioremap(P9_PERI_CRG, 0x1000);
	struct device_node *np;
	struct platform_device *pdev = NULL;

	if (!crg)
		return -ENOMEM;
	writel(0 | (BIT(6) << 16), crg + 0xb8);		/* clk_sd_muxsys = clk_factor_mmc0 (hiword mask) */
	writel(BIT(17), crg + 0x40);			/* clk_sd  (PEREN4) */
	writel(BIT(30), crg + 0x00);			/* hclk_sd (PEREN0) */
	writel(BIT(18) | BIT(24), crg + 0x94);		/* RSTDIS4: SD controller + SD_M */
	udelay(10);
	pr_info("p9test: sd clk 0xb8=0x%08x PERSTAT4=0x%08x RSTSTAT4=0x%08x\n",
		readl(crg + 0xb8), readl(crg + 0x4c), readl(crg + 0x98));
	iounmap(crg);
	np = of_find_node_by_path(P9_SD_NODE);
	if (np) {
		p9_set_prop_str(np, "status", "okay");
		pdev = of_platform_device_create(np, NULL, NULL);
		of_node_put(np);
	}
	pr_info("p9test: sd host device %s\n", pdev ? "created" : "FAILED");
	p9_save_log();
	return pdev ? 0 : -EIO;
}

static ssize_t p9_sd_write(struct file *f, const char __user *buf, size_t len, loff_t *off)
{
	int ret = p9_sd_bringup();

	return ret ? ret : len;
}

static const struct file_operations p9_sd_fops = {
	.write = p9_sd_write,
};

static int p9_sdio_bringup(void)
{
	void __iomem *crg = ioremap(P9_PERI_CRG, 0x1000);
	void __iomem *pmu = ioremap(P9_PMU_CLK32KB & PAGE_MASK, PAGE_SIZE);
	void __iomem *gp = ioremap(P9_GPIO_PWRON_BASE, 0x1000);
	void __iomem *gx = ioremap(P9_GPIO_XLDO_BASE, 0x1000);
	struct device_node *np;
	struct platform_device *pdev;
	int ret = -ENODEV;

	if (!crg || !pmu || !gp || !gx)
		goto out;
	pr_info("p9test: sdio step 1: clocks (div 16 -> 100 MHz) and gates\n");
	writel((15 << 7) | (0x780 << 16), crg + 0xb8);
	/* clk_sdio0_muxsy (bit 13) -> clkdiv_sdio0 (r16 does this); muxpl (bits 12:11) = 0 ->
	 * clk_ap_ppll0 1.44 GHz, which is running (ppll3 used by r16 may be off here) */
	/* muxsy = 0 -> clk_factor_mmc0 = 19.2 MHz / 6 = 3.2 MHz (always running). The
	 * clkdiv path needs the ppll "AP" branch (hisilicon,ppll-ctrl), which is off here. */
	writel(0 | (BIT(13) << 16), crg + 0xb8);
	pr_info("p9test: sdio clk reg 0xb8 = 0x%08x (div=%u muxsy=%u muxpl=%u)\n",
		readl(crg + 0xb8), ((readl(crg + 0xb8) >> 7) & 0xf) + 1,
		!!(readl(crg + 0xb8) & BIT(13)), (readl(crg + 0xb8) >> 11) & 3);
	writel(BIT(4) | (BIT(4) << 16), crg + 0xf4);	/* clkgt_sdio0: bit 4, hiword mask */
	writel(BIT(18), crg + 0x40);			/* clk_sdio0  (PEREN4) */
	writel(BIT(19), crg + 0x00);			/* hclk_sdio0 (PEREN0) */
	udelay(10);
	pr_info("p9test: sdio step 2: release reset (RSTDIS4 bit 19), RSTSTAT4 before=0x%08x\n",
		readl(crg + 0x98));
	writel(BIT(19), crg + 0x94);
	udelay(10);
	pr_info("p9test: sdio RSTSTAT4 after=0x%08x CLKSTAT4=0x%08x\n",
		readl(crg + 0x98), readl(crg + 0x4c));
	p9_save_log();
	/* apply the hi1102 node's "default" pin states (gpio/pin functions for power,
	 * 32k, wakeup); nothing in mainline binds that node, so do it by hand */
	/* vendor board.c: prepare_to_power_on() selects pinctrl "idle" (XLDO pin = GPIO),
	 * drives XLDO, then power_on pulse, then post_to_power_on() selects "default" */
	{
		struct device_node *hn = of_find_compatible_node(NULL, NULL, "hisilicon,hi1102");
		struct platform_device *hp = hn ? of_platform_device_create(hn, NULL, NULL) : NULL;
		struct pinctrl *pc = ERR_PTR(-ENODEV);
		struct pinctrl_state *st_idle = NULL, *st_def = NULL;

		if (!hp && hn)
			hp = of_find_device_by_node(hn);
		if (hp)
			pc = pinctrl_get(&hp->dev);	/* not devm: the hi1102 board driver probes this device later */
		if (!IS_ERR(pc)) {
			st_idle = pinctrl_lookup_state(pc, "idle");
			st_def = pinctrl_lookup_state(pc, "default");
		}
		pr_info("p9test: sdio step 3: Hi1102 power (pinctrl idle=%d default=%d) sdio_power=%d pwron_now=%d xldo_now=%d\n",
			!IS_ERR_OR_NULL(st_idle), !IS_ERR_OR_NULL(st_def), sdio_power,
			!!readl(gp + (BIT(3) << 2)), !!readl(gx + (BIT(3) << 2)));
		if (!sdio_power)
			goto skip_power;
		/* 32 kHz first and let it settle (vendor enables it at boot, long before) */
		/* clk_pmu32kb = PMIC reg 0x121 (<<2) BIT 1 (DT "hisilicon,clkgate" is <reg bit-index>;
		 * bit 0 is clk_pmu32ka). Earlier builds wrongly wrote bit 0 and clobbered bit 1. */
		pmu += P9_PMU_CLK32KB & ~PAGE_MASK;
		{
			u32 before = readl(pmu);

			writel(before | BIT(1), pmu);
			pr_info("p9test: pmu 32k reg before=0x%02x after=0x%02x\n", before, readl(pmu));
		}
		msleep(100);
		if (!IS_ERR_OR_NULL(st_idle))
			pinctrl_select_state(pc, st_idle);
		p9_pl061_set(gp, 3, 0);		/* make sure the chip is off */
		msleep(100);
		p9_pl061_set(gx, 3, 1);
		msleep(20);
		p9_pl061_set(gp, 3, 1);
		msleep(200);
		if (!IS_ERR_OR_NULL(st_def))
			pinctrl_select_state(pc, st_def);
		msleep(50);
skip_power:
		if (!IS_ERR(pc))
			pinctrl_put(pc);
		of_node_put(hn);
	}
	pr_info("p9test: hi1102 powered (32k=0x%x pwron=%d xldo=%d)\n", readl(pmu),
		!!readl(gp + (BIT(3) << 2)), !!readl(gx + (BIT(3) << 2)));
	p9_save_log();
	np = of_find_node_by_path("/dwmmc2@ff37d000");
	if (!np)
		goto out;
	pr_info("p9test: sdio step 4: enable node and probe dw_mmc-k3\n");
	p9_set_prop_str(np, "status", "okay");
	p9_save_log();
	pdev = of_platform_device_create(np, NULL, NULL);
	ret = pdev ? 0 : -EIO;
	pr_info("p9test: sdio host device %s\n", pdev ? "created" : "FAILED");
	of_node_put(np);
out:
	if (crg) iounmap(crg);
	if (gp) iounmap(gp);
	if (gx) iounmap(gx);
	p9_save_log();
	return ret;
}

/* Hook from Huawei's dw_mmc fork, called by the Hi1102 driver after it powers the chip
 * on or off: rescan the Wi-Fi slot. Clearing rescan_entered lets mmc_rescan() run again
 * on the non-removable slot (removes a dead card, attaches a new one, keeps a live one). */
void dw_mci_sdio_card_detect_change(void)
{
	struct device_node *np = of_find_node_by_path("/dwmmc2@ff37d000");
	struct platform_device *pdev = np ? of_find_device_by_node(np) : NULL;
	struct dw_mci *host = pdev ? platform_get_drvdata(pdev) : NULL;

	of_node_put(np);
	if (host && host->mmc) {
		pr_info("p9test: sdio card detect requested\n");
		host->mmc->rescan_entered = 0;
		mmc_detect_change(host->mmc, 0);
	} else {
		pr_err("p9test: sdio card detect: no dw_mmc host (write p9test/sdio first)\n");
	}
	if (pdev)
		put_device(&pdev->dev);
	p9_save_log();
}
EXPORT_SYMBOL(dw_mci_sdio_card_detect_change);

static ssize_t p9_sdio_write(struct file *f, const char __user *buf, size_t len, loff_t *off)
{
	int ret = p9_sdio_bringup();

	return ret ? ret : len;
}

static const struct file_operations p9_sdio_fops = {
	.write = p9_sdio_write,
};

/* save the log to pstore every 2 s so a hang still leaves a trace */
static struct delayed_work save_work;
static void p9_save_fn(struct work_struct *w)
{
	p9_save_log();
	schedule_delayed_work(&save_work, secs_to_jiffies(2));
}

static int __init p9test_early(void)
{
	if (!of_machine_is_compatible("hisilicon,hi6250"))
		return 0;	/* only ever poke Hi6250 MMIO */
	p9_fix_ramoops_dt();
	p9_fix_emmc();
	p9_fix_i2c4();
	p9_usb_phy_init();
	p9_fix_usb_dt();
	if (sdio_prep)
		p9_sdio_dt_prepare();
	p9_sd_dt_prepare();
	con_zone = p9_map_wc(P9_CON_PHYS, P9_CON_SIZE);
	con_buf = vmalloc(P9_CON_SIZE);
	wdt = ioremap(P9_WDT_BASE, 0x1000);
	pmu_rst = ioremap(P9_PMU_RESET_REG & PAGE_MASK, PAGE_SIZE);
	if (pmu_rst)
		pmu_rst += P9_PMU_RESET_REG & ~PAGE_MASK;
	nmi = ioremap(P9_NMI_LPM3_REG & PAGE_MASK, PAGE_SIZE);
	if (nmi)
		nmi += P9_NMI_LPM3_REG & ~PAGE_MASK;
	pmu_ssi = ioremap(P9_PMU_SSI_BASE, 0x1000);
	if (prod)
		keepalive = true;
	if (early_reason)	/* any reset from now on (watchdog too) stops in fastboot; prod: until boot_ok */
		p9_set_reason(P9_REASON_BOOTLOADER);
	atomic_notifier_chain_register(&panic_notifier_list, &p9_panic_nb);
	if (wdt && wdt_timeout) {
		/* SP805 runs from 32.768 kHz; it counts down twice (irq, then reset) */
		writel(SP805_UNLOCK_KEY, wdt + SP805_LOCK);
		writel(wdt_timeout * 32768 / 2, wdt + 0x00);	/* WDTLOAD */
		writel(0x3, wdt + 0x08);			/* WDTCONTROL: INTEN | RESEN */
		writel(0, wdt + SP805_LOCK);
		pr_info("p9test: SP805 armed, %us timeout, ctrl=0x%x\n", wdt_timeout,
			readl(wdt + 0x08));
	}
	p9_wdt_pet();
	hrtimer_setup(&pet_timer, p9_pet_fn, CLOCK_MONOTONIC, HRTIMER_MODE_REL);
	hrtimer_start(&pet_timer, ms_to_ktime(1000), HRTIMER_MODE_REL);
	register_restart_handler(&p9_restart_nb);
	hrtimer_setup(&shutdown_timer, p9_shutdown_fn, CLOCK_MONOTONIC, HRTIMER_MODE_REL);
	register_reboot_notifier(&p9_reboot_nb);
	if (early_success) {	/* the bootloader must never count our resets as boot failures (-> eRecovery) */
		void __iomem *kp_reg = ioremap(P9_PMU_KEYPOINT_REG & PAGE_MASK, PAGE_SIZE);

		if (kp_reg) {
			writel(P9_STAGE_BOOT_SUCCESS, kp_reg + (P9_PMU_KEYPOINT_REG & ~PAGE_MASK));
			iounmap(kp_reg);
		}
	}
	mark = (u32 *)p9_map_wc(P9_MARK_PHYS, PAGE_SIZE);
	if (mark)
		mark += 0xFF0 / sizeof(u32);
	if (!early_hook_ran && mark && mark[0] == P9_MARK_MAGIC && mark[1] == P9_MARK_BOOTING) {
		keep_log = true;
		pr_emerg("p9test: previous boot died before boot_ok (watchdog/thermal?), its log is kept; -> fastboot\n");
		p9_set_reason(P9_REASON_BOOTLOADER);
		emergency_restart();
	}
	p9_mark_set(P9_MARK_BOOTING);
	pr_info("p9test: watchdog feeder + bootloader-restart handler active (wdt=%p pmu=%p nmi=%p)\n",
		wdt, pmu_rst, nmi);
	return 0;
}
core_initcall(p9test_early);

static int __init p9test_late(void)
{
	struct dentry *d;

	if (!of_machine_is_compatible("hisilicon,hi6250"))
		return 0;	/* only ever poke Hi6250 MMIO */
	d = debugfs_create_dir("p9test", NULL);
	debugfs_create_file("sdio", 0200, d, NULL, &p9_sdio_fops);
	debugfs_create_file("sd", 0200, d, NULL, &p9_sd_fops);
	INIT_DELAYED_WORK(&save_work, p9_save_fn);
	INIT_DELAYED_WORK(&deadline_work, p9_deadline_fn);
	if (save_periodic)
		schedule_delayed_work(&save_work, secs_to_jiffies(2));
	pr_info("p9test: switches save_periodic=%d early_reason=%d sdio_prep=%d feed_grace=%u\n",
		save_periodic, early_reason, sdio_prep, feed_grace);
	if (prod) {
		if (boot_deadline && !boot_ok)
			schedule_delayed_work(&deadline_work, secs_to_jiffies(boot_deadline));
		pr_info("p9test: production mode: resets -> fastboot until boot_ok (deadline %us), then normal boot\n",
			boot_deadline);
		return 0;
	}
	INIT_DELAYED_WORK(&report_work, p9_report);
	schedule_delayed_work(&report_work, secs_to_jiffies(reboot_delay));
	pr_info("p9test: report + reboot to bootloader in %us\n", reboot_delay);
	return 0;
}
late_initcall_sync(p9test_late);
