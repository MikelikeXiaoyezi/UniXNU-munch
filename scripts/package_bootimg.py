#!/usr/bin/env python3
"""Pack the munch edk2-msm firmware into an Android boot header v3 image.

munch's stock ABL rejects the header-v1 image that edk2-msm's own build.sh
uses for `fastboot boot`; the stock boot image is header v3. This packer emits
v3 with the payload left on the ESP partition (ramdisk is empty).

kernel = gzip(BootShim.bin + SM8250_UEFI.fd) + munch.dtb
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import struct
import sys
from pathlib import Path

PAGE = 4096
HEADER_V3_SIZE = 1580


def pad(data: bytes, page: int = PAGE) -> bytes:
    return data + b"\x00" * ((-len(data)) % page)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fd", required=True, type=Path, help="SM8250_UEFI.fd")
    parser.add_argument("--dtb", required=True, type=Path, help="munch.dtb appended to the kernel")
    parser.add_argument("--shim", required=True, type=Path, help="tools/BootShim/BootShim.bin")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cmdline", default="")
    parser.add_argument("--os-version", type=lambda s: int(s, 0), default=0x0B000000)
    args = parser.parse_args()

    for path in (args.fd, args.dtb, args.shim):
        if not path.is_file():
            print(f"error: missing {path}", file=sys.stderr)
            return 2

    shim = args.shim.read_bytes()
    fd = args.fd.read_bytes()
    dtb = args.dtb.read_bytes()
    if not dtb[:4] == b"\xd0\x0d\xfe\xed":
        print("error: --dtb is not a compiled device tree", file=sys.stderr)
        return 2

    kernel = gzip.compress(shim + fd, mtime=0) + dtb
    ramdisk = b""

    header = bytearray(HEADER_V3_SIZE)
    header[0:8] = b"ANDROID!"
    struct.pack_into("<I", header, 8, len(kernel))
    struct.pack_into("<I", header, 12, len(ramdisk))
    struct.pack_into("<I", header, 16, args.os_version)
    struct.pack_into("<I", header, 20, HEADER_V3_SIZE)
    struct.pack_into("<I", header, 40, 3)  # header_version
    cmdline = args.cmdline.encode("ascii", "replace")[:1535]
    header[44:44 + len(cmdline)] = cmdline

    image = pad(bytes(header)) + pad(kernel) + pad(ramdisk)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)

    print(f"wrote {args.output} ({len(image)} bytes)")
    print(f"  kernel: {len(kernel)} bytes (gzip shim+fd {len(shim) + len(fd)}, dtb {len(dtb)})")
    print(f"  ramdisk: {len(ramdisk)} bytes (payload is on the ESP)")
    print(f"  sha256: {hashlib.sha256(image).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
