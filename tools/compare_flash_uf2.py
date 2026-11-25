#!/usr/bin/env python3
"""Compare all programmed UF2 bytes with a picotool full-flash BIN dump."""
import argparse
import hashlib
import struct
from pathlib import Path

BLOCK = 512


def compare(flash_path: Path, uf2_path: Path, base: int):
    flash, uf2 = flash_path.read_bytes(), uf2_path.read_bytes()
    checked = mismatches = missing = 0
    first = None
    for off in range(0, len(uf2), BLOCK):
        address = struct.unpack_from("<I", uf2, off + 12)[0]
        size = struct.unpack_from("<I", uf2, off + 16)[0]
        start = address - base
        expected = uf2[off + 32:off + 32 + size]
        if start < 0 or start + size > len(flash):
            missing += size
            continue
        actual = flash[start:start + size]
        checked += size
        if actual != expected:
            mismatches += sum(a != b for a, b in zip(actual, expected))
            if first is None:
                first = address + next(i for i, (a, b) in enumerate(zip(actual, expected)) if a != b)
    return {
        "flash_file": str(flash_path), "flash_bytes": len(flash),
        "flash_sha256": hashlib.sha256(flash).hexdigest(),
        "uf2_file": str(uf2_path), "uf2_sha256": hashlib.sha256(uf2).hexdigest(),
        "compared_payload_bytes": checked, "mismatched_payload_bytes": mismatches,
        "payload_bytes_outside_dump": missing,
        "first_mismatch_address": hex(first) if first is not None else None,
        "all_uf2_payload_matches": mismatches == 0 and missing == 0,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("flash_bin", type=Path)
    p.add_argument("uf2", type=Path)
    p.add_argument("--base", type=lambda x: int(x, 0), default=0x10000000)
    args = p.parse_args()
    import json
    print(json.dumps(compare(args.flash_bin, args.uf2, args.base), indent=2))


if __name__ == "__main__":
    main()
