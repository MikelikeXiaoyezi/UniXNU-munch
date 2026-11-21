#!/usr/bin/env python3
"""Create a FAT32 image without mtools.

The munch payload is a real ESP volume, not a Mu-Silicium initrd. This script
writes the files into a FAT32 image that EDK2's PartitionDxe + FatDxe (and
UniXNU.efi through EFI_SIMPLE_FILE_SYSTEM_PROTOCOL) can mount.

Usage:
    python3 make_fat32.py --output munch-esp.img --size-mib 176 \
        --label MUNCHESP --source build/payload

The image uses 512-byte clusters (the FAT32 minimum) so a 176 MiB volume stays
above the FAT32 cluster-count floor. Timestamps are fixed at 1980-01-01 so the
image is reproducible.
"""
from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SECTOR = 512
RESERVED_SECTORS = 32
NUM_FATS = 2
ROOT_CLUSTER = 2
FSINFO_SECTOR = 1
BACKUP_BOOT_SECTOR = 6
FSINFO_BACKUP_SECTOR = 7
FIXED_DATE = ((1980 - 1980) << 9) | (1 << 5) | 1
FIXED_TIME = 0
ATTR_DIR = 0x10
ATTR_ARCHIVE = 0x20
ATTR_LFN = 0x0F
EOC = 0x0FFFFFFF
VOLUME_LABEL = "MUNCHESP"


@dataclass
class Node:
    name: str
    is_dir: bool
    data: bytes = b""
    children: dict[str, "Node"] = field(default_factory=dict)
    first_cluster: int = 0
    clusters: int = 0
    parent: "Node | None" = None
    short_name: bytes = b""

    @property
    def size(self) -> int:
        return 0 if self.is_dir else len(self.data)


def checksum(short_name: bytes) -> int:
    value = 0
    for byte in short_name:
        value = (((value & 1) << 7) + (value >> 1) + byte) & 0xFF
    return value


INVALID = set('\\/:*?"<>|')


def make_short_name(name: str, used: set[bytes]) -> bytes:
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = "".join(c for c in stem.upper() if c not in INVALID and c not in " .")
    ext = "".join(c for c in ext.upper() if c not in INVALID and c not in " .")
    if not stem:
        stem = "FILE"
    stem = stem[:8]
    ext = ext[:3]
    candidate = (stem.ljust(8) + ext.ljust(3)).encode("ascii", "replace")
    if len(stem) + len(ext) > 11 or any(ord(c) > 0x7F for c in stem + ext):
        base = (stem[:6] or "FILE") + "~1"
        candidate = (base.ljust(8) + ext.ljust(3)).encode("ascii", "replace")
    counter = 1
    while candidate in used:
        counter += 1
        base = (stem[:6] or "FILE") + f"~{counter}"
        candidate = (base.ljust(8) + ext.ljust(3)).encode("ascii", "replace")
    used.add(candidate)
    return candidate


def lfn_entries(name: str, short_name: bytes) -> bytes:
    encoded = name.encode("utf-16-le")
    chunks = [encoded[i:i + 26] for i in range(0, len(encoded), 26)]
    if len(encoded) % 2:
        chunks[-1] += b"\x00\x00"
    if len(chunks) > 20:
        raise ValueError(f"long file name too long: {name}")
    total = len(chunks)
    entries = bytearray()
    chk = checksum(short_name)
    for index in range(total - 1, -1, -1):
        chunk = chunks[index]
        chunk = chunk + b"\xFF" * (26 - len(chunk))
        ordinal = index + 1
        if index == total - 1:
            ordinal |= 0x40
        entry = bytearray(32)
        entry[0] = ordinal
        entry[1:11] = chunk[0:10]
        entry[11] = ATTR_LFN
        entry[12] = 0
        entry[13] = chk
        entry[14:26] = chunk[10:22]
        entry[26:28] = b"\x00\x00"
        entry[28:32] = chunk[22:26]
        entries += entry
    return bytes(entries)


def dirent(short_name: bytes, attr: int, cluster: int, size: int) -> bytes:
    entry = bytearray(32)
    entry[0:11] = short_name
    entry[11] = attr
    entry[12] = 0
    entry[13] = 0
    struct.pack_into("<H", entry, 14, FIXED_TIME)
    struct.pack_into("<H", entry, 16, FIXED_DATE)
    struct.pack_into("<H", entry, 18, FIXED_DATE)
    struct.pack_into("<H", entry, 20, cluster >> 16)
    struct.pack_into("<H", entry, 22, FIXED_TIME)
    struct.pack_into("<H", entry, 24, FIXED_DATE)
    struct.pack_into("<H", entry, 26, cluster & 0xFFFF)
    struct.pack_into("<I", entry, 28, size)
    return bytes(entry)


def build_tree(source: Path) -> Node:
    root = Node("", True)

    def walk(path: Path, node: Node) -> None:
        used: set[bytes] = set()
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                sub = Node(child.name, True, parent=node)
                walk(child, sub)
                node.children[child.name] = sub
            else:
                node.children[child.name] = Node(child.name, False, data=child.read_bytes(), parent=node)
            node.children[child.name].short_name = make_short_name(child.name, used)

    walk(source, root)
    return root


def collect(node: Node, out: list[Node]) -> None:
    for child in node.children.values():
        out.append(child)
        if child.is_dir:
            collect(child, out)


def dir_bytes(node: Node, cluster: int) -> bytes:
    entries = bytearray()
    if node.parent is None:
        entries += dirent(VOLUME_LABEL.encode("ascii", "replace").ljust(11)[:11], 0x08, 0, 0)
    if node.parent is not None:
        parent_cluster = 0 if node.parent.parent is None and node.parent.name == "" else node.parent.first_cluster
        entries += dirent(b"." .ljust(11), ATTR_DIR, node.first_cluster, 0)
        entries += dirent(b"..".ljust(11), ATTR_DIR, parent_cluster, 0)
    for child in sorted(node.children.values(), key=lambda n: (not n.is_dir, n.name.lower())):
        entries += lfn_entries(child.name, child.short_name)
        entries += dirent(child.short_name, ATTR_DIR if child.is_dir else ATTR_ARCHIVE,
                          child.first_cluster, child.size)
    entries += b"\x00" * 32
    pad = (-len(entries)) % (SECTOR)
    return bytes(entries) + b"\x00" * pad


def build_image(root: Node, total_bytes: int, label: str) -> bytes:
    if total_bytes % SECTOR:
        raise ValueError("image size must be a multiple of 512")
    total_sectors = total_bytes // SECTOR
    cluster_bytes = SECTOR
    # Iterate to a self-consistent FAT size and cluster count.
    fat_sectors = 1
    while True:
        data_sectors = total_sectors - RESERVED_SECTORS - NUM_FATS * fat_sectors
        clusters = data_sectors // (cluster_bytes // SECTOR)
        needed = ((clusters + 2) * 4 + SECTOR - 1) // SECTOR
        if needed <= fat_sectors:
            break
        fat_sectors = needed
    if clusters < 65525:
        raise ValueError(f"too small for FAT32: {clusters} clusters (need >= 65525); use at least 34 MiB")
    data_start_sector = RESERVED_SECTORS + NUM_FATS * fat_sectors

    all_nodes: list[Node] = []
    collect(root, all_nodes)
    root.first_cluster = ROOT_CLUSTER
    root.clusters = max(1, (len(dir_bytes(root, ROOT_CLUSTER)) + SECTOR - 1) // SECTOR)
    next_cluster = ROOT_CLUSTER + root.clusters
    for node in all_nodes:
        node.first_cluster = next_cluster
        node.clusters = max(1, (len(dir_bytes(node, node.first_cluster)) if node.is_dir else node.size
                                + cluster_bytes - 1) // cluster_bytes)
        next_cluster += node.clusters
    if next_cluster - 2 > clusters:
        raise ValueError(f"payload does not fit: needs {next_cluster - 2} clusters, image has {clusters}")

    fat = [0] * (clusters + 2)
    fat[0] = 0x0FFFFFF8  # media descriptor
    fat[1] = 0x0FFFFFFF  # end of chain

    def chain(first: int, count: int) -> None:
        for i in range(count):
            cur = first + i
            nxt = cur + 1 if i + 1 < count else EOC
            fat[cur] = nxt

    chain(root.first_cluster, root.clusters)
    for node in all_nodes:
        chain(node.first_cluster, node.clusters)

    fat_bytes = bytearray(fat_sectors * SECTOR)
    for index, value in enumerate(fat):
        struct.pack_into("<I", fat_bytes, index * 4, value & 0x0FFFFFFF)
    for index in range(clusters + 2, fat_sectors * SECTOR // 4):
        struct.pack_into("<I", fat_bytes, index * 4, 0)

    image = bytearray(total_bytes)
    # Boot sector
    bs = bytearray(SECTOR)
    bs[0:3] = b"\xEB\x58\x90"
    bs[3:11] = b"MSWIN4.1"
    struct.pack_into("<H", bs, 11, SECTOR)
    bs[13] = 1  # sectors per cluster
    struct.pack_into("<H", bs, 14, RESERVED_SECTORS)
    bs[16] = NUM_FATS
    struct.pack_into("<H", bs, 17, 0)
    struct.pack_into("<H", bs, 19, 0)
    bs[21] = 0xF8
    struct.pack_into("<H", bs, 22, 0)
    struct.pack_into("<H", bs, 24, 63)
    struct.pack_into("<H", bs, 26, 255)
    struct.pack_into("<I", bs, 28, 0)
    struct.pack_into("<I", bs, 32, total_sectors)
    struct.pack_into("<I", bs, 36, fat_sectors)
    struct.pack_into("<H", bs, 40, 0)
    struct.pack_into("<H", bs, 42, 0)
    struct.pack_into("<I", bs, 44, ROOT_CLUSTER)
    struct.pack_into("<H", bs, 48, FSINFO_SECTOR)
    struct.pack_into("<H", bs, 50, BACKUP_BOOT_SECTOR)
    bs[64] = 0x80
    bs[66] = 0x29
    struct.pack_into("<I", bs, 67, 0x4D554E43)  # 'MUNC'
    bs[71:82] = label.upper().encode("ascii", "replace").ljust(11)[:11]
    bs[82:90] = b"FAT32   "
    bs[510:512] = b"\x55\xAA"
    image[0:SECTOR] = bs
    image[BACKUP_BOOT_SECTOR * SECTOR:(BACKUP_BOOT_SECTOR + 1) * SECTOR] = bs

    fsinfo = bytearray(SECTOR)
    struct.pack_into("<I", fsinfo, 0, 0x41615252)
    struct.pack_into("<I", fsinfo, 484, 0x61417272)
    struct.pack_into("<I", fsinfo, 488, clusters - (next_cluster - 2))
    struct.pack_into("<I", fsinfo, 492, next_cluster)
    struct.pack_into("<I", fsinfo, 508, 0xAA550000)
    image[FSINFO_SECTOR * SECTOR:(FSINFO_SECTOR + 1) * SECTOR] = fsinfo
    image[FSINFO_BACKUP_SECTOR * SECTOR:(FSINFO_BACKUP_SECTOR + 1) * SECTOR] = fsinfo

    for copy in range(NUM_FATS):
        start = (RESERVED_SECTORS + copy * fat_sectors) * SECTOR
        image[start:start + len(fat_bytes)] = fat_bytes

    def cluster_offset(cluster: int) -> int:
        return (data_start_sector + (cluster - 2) * (cluster_bytes // SECTOR)) * SECTOR

    def write_node(node: Node) -> None:
        data = dir_bytes(node, node.first_cluster) if node.is_dir else node.data
        padded = data + b"\x00" * ((-len(data)) % cluster_bytes)
        start = cluster_offset(node.first_cluster)
        image[start:start + len(padded)] = padded
        if node.is_dir:
            for child in node.children.values():
                write_node(child)

    write_node(root)
    return bytes(image)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path,
                        help="directory copied to the FAT32 root")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--size-mib", type=int, default=176)
    parser.add_argument("--label", default="MUNCHESP")
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"error: {args.source} is not a directory", file=sys.stderr)
        return 2
    global VOLUME_LABEL
    VOLUME_LABEL = args.label
    root = build_tree(args.source)
    image = build_image(root, args.size_mib * 1024 * 1024, args.label)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    print(f"wrote {args.output} ({len(image)} bytes, FAT32, label {args.label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
