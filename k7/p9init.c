/* Minimal /init for P9 Lite mainline boot tests: say hello, then wait.
 * The kernel's p9test driver reboots into the bootloader after its report. */
#include <fcntl.h>
#include <unistd.h>
#include <sys/mount.h>
#include <sys/stat.h>

int main(void)
{
	mkdir("/dev", 0755);
	mount("devtmpfs", "/dev", "devtmpfs", 0, NULL);
	int fd = open("/dev/kmsg", O_WRONLY);
	if (fd >= 0) {
		const char msg[] = "<6>p9init: userspace /init reached on mainline kernel\n";
		write(fd, msg, sizeof(msg) - 1);
		close(fd);
	}
	for (;;)
		pause();
}
