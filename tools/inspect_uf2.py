#!/usr/bin/env python3
"""Validate UF2 block structure and report mapped payload SHA-256."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

BLOCK = 512
MAGIC0, MAGIC1, MAGIC_END = 0x0A324655, 0x9E5D5157, 0x0AB16F30


def inspect(path: Path):
    data = path.read_bytes()
    if len(data) % BLOCK:
        raise ValueError(f"file size {len(data)} is not a multiple of 512")
    block_count, writes, addresses, families = len(data) // BLOCK, 0, [], set()
    payload = bytearray()
    for offset in range(0, len(data), BLOCK):
        magic0, magic1, flags, address, size, number, total, family = struct.unpack_from("<8I", data, offset)
        end = struct.unpack_from("<I", data, offset + 508)[0]
        if (magic0, magic1, end) != (MAGIC0, MAGIC1, MAGIC_END):
            raise ValueError(f"invalid magic in block {offset // BLOCK}")
        if size > 476:
            raise ValueError(f"invalid payload size {size} in block {offset // BLOCK}")
        if number != offset // BLOCK or total != block_count:
            raise ValueError(f"block sequence mismatch in block {offset // BLOCK}: {number}/{total}")
        writes += size
        addresses.append((address, size))
        families.add(family if flags & 0x2000 else None)
        payload.extend(data[offset + 32:offset + 32 + size])
    payload_blocks = sorted((address, address + size) for address, size in addresses if size)
    ranges = []
    for start, end in payload_blocks:
        if ranges and start == ranges[-1][1]:
            ranges[-1][1] = end
        else:
            ranges.append([start, end])
    contiguous = len(ranges) == 1
    strings = [x.decode("ascii", "replace") for x in re.findall(rb"[\x20-\x7e]{6,}", payload)]
    return {
        "path": str(path), "file_bytes": len(data), "block_count": block_count,
        "payload_bytes": writes, "payload_sha256_concatenated": hashlib.sha256(payload).hexdigest(),
        "block_sequence_valid": True, "address_ranges": [[hex(a), hex(b)] for a, b in ranges],
        "contiguous": contiguous, "family_ids": sorted({hex(x) if x is not None else None for x in families}, key=str),
        "strings": strings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("uf2", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = inspect(args.uf2)
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.json:
        args.json.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
