#!/usr/bin/env python3
"""Convert HEIC/HEIF images to JPEG without resizing."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()

HEIC_SUFFIXES = {".heic", ".heif"}


def convert(src: Path, dst_dir: Path, quality: int) -> Path:
    dst = dst_dir / (src.stem + ".jpg")
    img = Image.open(src)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(dst, format="JPEG", quality=quality, subsampling=0)
    return dst


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert HEIC/HEIF images to JPEG")
    parser.add_argument("input", nargs="+", help="HEIC files or directories")
    parser.add_argument("-o", "--output", help="Output directory (default: same as input)")
    parser.add_argument("-q", "--quality", type=int, default=95, help="JPEG quality 1-100 (default: 95)")
    parser.add_argument("--delete-originals", action="store_true", help="Delete original HEIC files after conversion")
    args = parser.parse_args()

    paths: list[Path] = []
    for inp in args.input:
        p = Path(inp)
        if p.is_dir():
            paths.extend(f for f in p.rglob("*") if f.suffix.lower() in HEIC_SUFFIXES)
        elif p.is_file() and p.suffix.lower() in HEIC_SUFFIXES:
            paths.append(p)
        else:
            print(f"skip: {p} (not a HEIC file or directory)", file=sys.stderr)

    if not paths:
        print("No HEIC files found.", file=sys.stderr)
        sys.exit(1)

    ok = fail = 0
    for src in sorted(paths):
        dst_dir = Path(args.output) if args.output else src.parent
        dst_dir.mkdir(parents=True, exist_ok=True)
        try:
            dst = convert(src, dst_dir, args.quality)
            size_mb = dst.stat().st_size / 1_048_576
            print(f"  {src.name} → {dst.name} ({size_mb:.1f} MB)")
            if args.delete_originals:
                src.unlink()
            ok += 1
        except Exception as exc:
            print(f"  ERROR {src.name}: {exc}", file=sys.stderr)
            fail += 1

    print(f"\n{ok} converted{f', {fail} failed' if fail else ''}.")


if __name__ == "__main__":
    main()
