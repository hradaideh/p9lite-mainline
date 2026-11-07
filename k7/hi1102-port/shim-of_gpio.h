/* SPDX-License-Identifier: GPL-2.0 */
/* p9 shim: linux/of_gpio.h was removed from mainline. Legacy global GPIO number lookup
 * for the Hi1102 board code, built on the current gpiolib API. */
#ifndef __P9_SHIM_OF_GPIO_H
#define __P9_SHIM_OF_GPIO_H
#include <linux/of.h>
#include <linux/gpio/driver.h>

static inline int of_get_named_gpio(const struct device_node *np, const char *prop, int idx)
{
	struct of_phandle_args a;
	struct gpio_device *g;
	int ret = of_parse_phandle_with_args(np, prop, "#gpio-cells", idx, &a);

	if (ret)
		return ret;
	g = gpio_device_find_by_fwnode(of_fwnode_handle(a.np));
	of_node_put(a.np);
	if (!g)
		return -EPROBE_DEFER;
	ret = gpio_device_get_base(g) + a.args[0];
	gpio_device_put(g);
	return ret;
}
#define of_get_named_gpio_flags(np, p, i, f) of_get_named_gpio(np, p, i)
#define of_get_gpio(np, i) of_get_named_gpio(np, "gpios", i)
#endif
