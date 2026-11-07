// SPDX-License-Identifier: GPL-2.0
/* p9: Huawei vendor-kernel services the Hi1102 driver calls that mainline does not have.
 * Each returns the "feature absent" answer the driver already handles. */
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/errno.h>

/* sensorhub (iomcu): not in MCU mode, so the bfgx wake path skips the iomcu wait */
int getSensorMcuMode(void) { return 0; }
int get_iomcu_power_state(void) { return 0; }

/* GPS platform glue (gps_plat_hi6250.c) is not built */
int hi_gps_plat_init(void) { return 0; }
void hi_gps_plat_exit(void) { }

/* Hi1102 is this board's connectivity chip */
bool isMyConnectivityChip(char *name) { return true; }

/* ponytail: NVE (factory MAC "MACWLAN" + RF calibration) lives in the nvme partition;
 * unread for now, so the driver takes its no-NVE fallback. Parse mmcblk0p7 to fix. */
struct hisi_nve_info_user;
int hisi_nve_direct_access(struct hisi_nve_info_user *u)
{
	pr_info("p9: NVE not available, Hi1102 uses default MAC/calibration\n");
	return -ENODEV;
}

/* Huawei netfilter wake-filter hooks: no filter framework in mainline */
int hw_register_wlan_filter(void *ops) { return 0; }
int hw_unregister_wlan_filter(void) { return 0; }
int hw_set_net_filter_enable(int on) { return 0; }
EXPORT_SYMBOL(hw_register_wlan_filter);
EXPORT_SYMBOL(hw_unregister_wlan_filter);
EXPORT_SYMBOL(hw_set_net_filter_enable);
