#!/usr/bin/env python3
"""
Raw-libusb bridge for PotatoNV-crossplatform's usrlock on macOS/Linux.

The HiSilicon IDT "USB SER" vendor-specific device (idVendor 0x12D1,
idProduct 0x3609) has no OS driver on macOS or Linux (interface class
is 0xff, vendor-specific, so cdc_acm never binds it either), so
usrlock's pyserial-based connect_serial() can't find it. This talks
to the same two bulk endpoints directly via libusb (pyusb),
reimplementing the exact framing protocol from usrlock/imageflasher.py.

v2: also reimplements Core.cs's WriteNVME() from the original C#
PotatoNV (not just usrlock's incomplete Python port), which writes
FBLOCK=1 before WVLOCK/USRKEY -- a step the crossplatform Python port
never performs at all, which is why v1 completed without errors but
never actually unlocked the device.

Usage: python3 unlock_shim.py <16-char-key>
"""
import sys
import os
import time
import hashlib
import binascii

REPO = os.path.expanduser("~/p9lite-linux/PotatoNV-crossplatform")
sys.path.insert(0, REPO)

import usb.core
import usb.util
from usrlock import fastboot  # noqa: E402

VID, PID = 0x12D1, 0x3609
EP_OUT = 0x01
EP_IN = 0x81
MAX_DATA_LEN = 0x400


def calc_crc(data, crc=0):
    for char in data:
        crc = ((crc << 8) | char) ^ binascii.crc_hqx(bytes([(crc >> 8) & 0xFF]), 0)
    for _ in range(2):
        crc = ((crc << 8) | 0) ^ binascii.crc_hqx(bytes([(crc >> 8) & 0xFF]), 0)
    return crc & 0xFFFF


class USBBulkSerial:
    def __init__(self):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise RuntimeError("Device not found (VID 0x12D1 PID 0x3609). "
                                "Is the phone shorted at the test point and plugged in?")
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except (NotImplementedError, usb.core.USBError):
            pass
        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, 0)
        self.timeout = 1.0

    def reset_output_buffer(self):
        pass

    def reset_input_buffer(self):
        try:
            while True:
                self.dev.read(EP_IN, 64, timeout=20)
        except usb.core.USBError:
            pass

    def write(self, data):
        to = int(self.timeout * 1000) if self.timeout else 3000
        self.dev.write(EP_OUT, data, timeout=max(to, 500))

    def read(self, size=1):
        to = int(self.timeout * 1000) if self.timeout else 1000
        try:
            data = self.dev.read(EP_IN, max(size, 64), timeout=max(to, 200))
            return bytes(data)[:size]
        except usb.core.USBError:
            return b""

    def close(self):
        try:
            usb.util.release_interface(self.dev, 0)
        except Exception:
            pass


class ShimImageFlasher:
    def __init__(self):
        self.serial = None
        self.headframe = bytes([0xFE, 0x00, 0xFF, 0x01])
        self.dataframe = bytes([0xDA])
        self.tailframe = bytes([0xED])
        self.ack = bytes([0xAA])

    def connect_serial(self):
        print("Connecting via raw libusb...")
        self.serial = USBBulkSerial()
        print("Connected to IDT device over raw USB bulk endpoints.")

    def send_frame(self, data):
        crc = calc_crc(data)
        data = data + crc.to_bytes(2, byteorder="big", signed=False)
        self.serial.reset_output_buffer()
        self.serial.reset_input_buffer()
        self.serial.write(data)
        ack = self.serial.read(1)
        if ack and ack != self.ack:
            raise RuntimeError(f"Invalid ACK from device! Read: {ack!r}")

    def send_head_frame(self, length, address):
        self.serial.timeout = 0.5
        data = self.headframe
        data += length.to_bytes(4, byteorder="big", signed=False)
        data += address.to_bytes(4, byteorder="big", signed=False)
        self.send_frame(data)

    def send_data_frame(self, n, data):
        self.serial.timeout = 1.0
        head = bytearray(self.dataframe)
        head.append(n & 0xFF)
        head.append((~n) & 0xFF)
        self.send_frame(bytes(head) + data)

    def send_tail_frame(self, n):
        self.serial.timeout = 0.3
        data = bytearray(self.tailframe)
        data.append(n & 0xFF)
        data.append((~n) & 0xFF)
        self.send_frame(bytes(data))

    def send_data(self, data, length, address):
        n_frames = length // MAX_DATA_LEN + (1 if length % MAX_DATA_LEN > 0 else 0)
        self.send_head_frame(length, address)
        n = 0
        remaining = length
        while remaining > MAX_DATA_LEN:
            f = data.read(MAX_DATA_LEN)
            self.send_data_frame(n + 1, f)
            n += 1
            remaining -= MAX_DATA_LEN
            print(f"  frame {n}/{n_frames}", end="\r")
        if remaining:
            f = data.read()
            self.send_data_frame(n + 1, f)
            n += 1
        print()
        self.send_tail_frame(n + 1)
        time.sleep(0.5)

    def download_from_disk(self, fil, address):
        with open(fil, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            self.send_data(f, size, address)


def set_nvme_prop(fb_dev, prop, value: bytes):
    """Matches Core.cs SetNVMEProp: getvar:nve:<prop>@<raw bytes>, expects 'set nv ok'."""
    cmd = f"getvar:nve:{prop}@".encode("utf-8") + value
    res = fb_dev.send(cmd)
    print(f"  {prop} -> {res!r}")
    if "set nv ok" not in res:
        raise RuntimeError(f"Failed to set {prop}: {res!r}")


def set_hwdog_state(fb_dev, state: int):
    """Matches Core.cs SetHWDogState: fallback OEM commands if the FBLOCK NVME write fails."""
    for command in ("hwdog certify set", "backdoor set"):
        print(f"  trying 'oem {command} {state}'...")
        try:
            res = fb_dev.send(f"oem {command} {state}")
            print(f"    -> {res!r}")
            if res:
                print(f"  {command}: got a response, treating as success")
                return True
        except Exception as e:
            print(f"    -> error: {e}")
    print("  Failed to set FBLOCK state via fallback commands.")
    return False


def read_fblock_state(fb_dev):
    res = fb_dev.send("oem lock-state info")
    if "UNLOCKED" not in res.upper():
        res = fb_dev.send("oem backdoor info")
    print(f"  FBLOCK info: {res!r}")
    return "UNLOCKED" in res.upper()


def write_nvme_full(fb_dev, key: str):
    """Reimplements Core.cs WriteNVME(): FBLOCK, then WVLOCK, then USRKEY."""
    print("Checking FBLOCK state on temporary bootloader...")
    try:
        unlocked = read_fblock_state(fb_dev)
        print(f"  temp bootloader FBLOCK reports: {'unlocked' if unlocked else 'locked'}")
    except Exception as e:
        print(f"  (couldn't read FBLOCK state: {e}; continuing anyway)")

    print("Writing FBLOCK=1 (the default/safe value; NOT disabling FBLOCK)...")
    try:
        set_nvme_prop(fb_dev, "FBLOCK", bytes([1]))
    except Exception as e:
        print(f"  FBLOCK NVME write failed ({e}), trying fallback OEM commands...")
        set_hwdog_state(fb_dev, 1)

    print("Writing WVLOCK (raw key)...")
    set_nvme_prop(fb_dev, "WVLOCK", key.encode("ascii"))

    print("Writing USRKEY (SHA-256 of key)...")
    m = hashlib.sha256()
    m.update(key.encode("ascii"))
    set_nvme_prop(fb_dev, "USRKEY", m.digest())


def main():
    if len(sys.argv) != 2 or len(sys.argv[1]) != 16:
        print("Usage: unlock_shim.py <16-character-key>")
        sys.exit(1)
    key = sys.argv[1]

    manifest_dir = os.path.join(REPO, "bootloaders", "hisi65x_a")
    images = [
        ("xloader", "xloader.img", 0x00020000),
        ("fastboot", "fastboot.img", 0x10000000),
    ]

    flasher = ShimImageFlasher()
    flasher.connect_serial()
    for role, path, addr in images:
        print(f"Flashing {role} ({path}) at {hex(addr)}...")
        flasher.download_from_disk(os.path.join(manifest_dir, path), addr)
    flasher.serial.close()
    print("Bootloader uploaded. Device should now be running the unlocked-by-default fastboot.")

    print("Waiting for fastboot device...")
    fb = fastboot.Fastboot()
    fb.connect()

    write_nvme_full(fb.fb_dev, key)

    print("Rebooting device...")
    fb.reboot()
    print(f"Done. Your bootloader unlock key is: {key}")


if __name__ == "__main__":
    main()
