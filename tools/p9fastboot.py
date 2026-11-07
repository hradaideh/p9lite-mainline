#!/usr/bin/env python3
"""Minimal fastboot client for the Huawei P9 Lite bootloader (hi6250, "Fastboot2.0").

Modern AOSP fastboot (v35+) sends queries such as getvar:max-download-size and
getvar:is-logical:<part> before flashing. This old Huawei bootloader never answers
them, so the stock tool hangs and leaves the bootloader wedged. This client speaks
only the basic protocol: getvar:<known var>, download, flash, reboot, reboot-bootloader.

Usage:
  p9fastboot.py devices
  p9fastboot.py getvar product
  p9fastboot.py flash boot boot.img
  p9fastboot.py reboot | reboot-bootloader
  p9fastboot.py wait [seconds]        # wait until the device shows up
"""
import sys, time
import usb.core, usb.util, usb.backend.libusb1

VID, PID = 0x18d1, 0xd00d
CHUNK = 1024 * 1024          # bulk write size per call
TIMEOUT_MS = 10000


def backend():
    for lib in ('/opt/homebrew/lib/libusb-1.0.dylib', '/usr/local/lib/libusb-1.0.dylib', None):
        be = usb.backend.libusb1.get_backend(find_library=(lambda x, l=lib: l) if lib else None)
        if be:
            return be
    raise SystemExit('libusb not found')


def find():
    return usb.core.find(idVendor=VID, idProduct=PID, backend=backend())


class Fastboot:
    def __init__(self, dev):
        self.dev = dev
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
        except (NotImplementedError, usb.core.USBError):
            pass
        dev.set_configuration()
        intf = dev.get_active_configuration()[(0, 0)]
        self.ep_out = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        self.ep_in = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)

    def _read(self, timeout=TIMEOUT_MS):
        while True:
            r = bytes(self.ep_in.read(256, timeout)).decode(errors='replace')
            kind, msg = r[:4], r[4:]
            if kind == 'INFO':
                print('(bootloader) ' + msg)
                continue
            return kind, msg

    def cmd(self, c, timeout=TIMEOUT_MS):
        self.ep_out.write(c.encode(), timeout)
        kind, msg = self._read(timeout)
        if kind == 'FAIL':
            raise SystemExit(f'FAILED ({c}): {msg}')
        return kind, msg

    def download(self, data):
        kind, msg = self.cmd('download:%08x' % len(data))
        if kind != 'DATA':
            raise SystemExit(f'unexpected reply to download: {kind}{msg}')
        t0 = time.time()
        for off in range(0, len(data), CHUNK):
            self.ep_out.write(data[off:off + CHUNK], 30000)
        kind, msg = self._read(30000)
        if kind != 'OKAY':
            raise SystemExit(f'download failed: {kind}{msg}')
        print(f'Sent {len(data)//1024} KB in {time.time()-t0:.2f}s')


def main(a):
    if not a or a[0] == 'devices':
        d = find()
        print(f'{d.serial_number}\tfastboot' if d else 'no device')
        return
    if a[0] == 'wait':
        end = time.time() + (float(a[1]) if len(a) > 1 else 60)
        while time.time() < end:
            if find():
                print('device present'); return
            time.sleep(1)
        raise SystemExit('timeout waiting for fastboot device')
    d = find()
    if not d:
        raise SystemExit('no fastboot device')
    fb = Fastboot(d)
    if a[0] == 'getvar':
        print(a[1] + ': ' + fb.cmd('getvar:' + a[1])[1])
    elif a[0] == 'flash':
        part, img = a[1], open(a[2], 'rb').read()
        fb.download(img)
        t0 = time.time()
        fb.cmd('flash:' + part, timeout=60000)
        print(f'Wrote {part} in {time.time()-t0:.2f}s')
    elif a[0] == 'raw':  # read-only queries only, e.g. raw "oem get-bootinfo"
        print(fb.cmd(a[1]))
    elif a[0] in ('reboot', 'reboot-bootloader'):
        try:
            fb.cmd(a[0])
        except usb.core.USBError:
            pass
        print('rebooting')
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
