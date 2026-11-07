#!/usr/bin/env python3
# Prepend a 0x180000-byte stub to a mainline arm64 Image so that, when the Huawei
# bootloader loads it at 0x480000 (as it does for the 4.4 kernel), the real Image
# starts at 0x600000 (2 MiB aligned, as required by kernels with text_offset=0).
# The stub carries a valid arm64 Image header (magic "ARM\x64") in case the
# bootloader checks it; its first instruction is "b #0x180000".
import struct, sys
src, dst = sys.argv[1], sys.argv[2]
PAD = 0x180000
img = open(src, 'rb').read()
assert img[0x38:0x3c] == b'ARM\x64', 'input is not an arm64 Image'
stub = bytearray(PAD)
b_insn = 0x14000000 | ((PAD // 4) & 0x3ffffff)
struct.pack_into('<I', stub, 0x00, b_insn)          # code0: branch to real Image
struct.pack_into('<I', stub, 0x04, 0)               # code1
struct.pack_into('<Q', stub, 0x08, 0x80000)         # text_offset like the 4.4 kernel
struct.pack_into('<Q', stub, 0x10, PAD + len(img))  # image_size
struct.pack_into('<Q', stub, 0x18, 0xa)             # flags: LE, 4K pages, anywhere
stub[0x38:0x3c] = b'ARM\x64'
open(dst, 'wb').write(bytes(stub) + img)
print('stub', hex(b_insn), 'out size', PAD + len(img))
