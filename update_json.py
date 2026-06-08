#!/usr/bin/env python3
"""
Build config.json from per-firmware metadata.

Usage:
  python3 update_json.py
  python3 update_json.py /Users/dominh/Desktop/AI_CODE/xiaozhi_firmware
  python3 update_json.py --bootstrap-from-config

Each firmware folder can contain firmware.json:
  firmware/<version>/<board_id>/firmware.json

Static fields are read from firmware.json. The generated config.json always uses
the version and firmware path inferred from the folder name, so new releases only
need a new firmware/<version>/<board_id>/merged_firmware.bin plus metadata.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


CONFIG_NAME = "config.json"
METADATA_NAME = "firmware.json"
FIRMWARE_FILE = "merged_firmware.bin"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DEFAULT_HOTWORD = "alexa"


def relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first_image_in(folder: Path, root: Path) -> str:
    for item in sorted(folder.iterdir()):
        if item.is_file() and item.suffix.lower() in IMAGE_EXTS:
            return relpath(item, root)
    return ""


def entry_from_metadata(meta_path: Path, root: Path) -> dict[str, Any]:
    board_dir = meta_path.parent
    version_dir = board_dir.parent
    board_id = board_dir.name
    version = version_dir.name

    metadata = load_json(meta_path)
    if not isinstance(metadata, dict):
        raise ValueError(f"{meta_path} must contain a JSON object")

    entry: dict[str, Any] = {}
    entry["title"] = metadata.get("title") or board_id
    entry["board"] = metadata.get("board") or ""
    entry["display"] = metadata.get("display") or ""
    entry["img_schematic"] = metadata.get("img_schematic") or first_image_in(board_dir, root)
    entry["version"] = version
    entry["hotword"] = metadata.get("hotword") or DEFAULT_HOTWORD
    entry["firmware"] = relpath(board_dir / FIRMWARE_FILE, root)

    return entry


def build_config(root: Path) -> list[dict[str, Any]]:
    metadata_files = sorted((root / "firmware").glob(f"*/*/{METADATA_NAME}"))
    entries = [entry_from_metadata(path, root) for path in metadata_files]
    entries.sort(key=lambda item: (item.get("version", ""), item.get("title", "")))
    return entries


def copy_image_to_stable_folder(root: Path, old_image_ref: str, board_id: str) -> str:
    if not old_image_ref:
        return ""

    old_image = root / old_image_ref
    if not old_image.exists() or old_image.suffix.lower() not in IMAGE_EXTS:
        return old_image_ref

    dest = root / "images" / board_id / old_image.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(old_image, dest)
    return relpath(dest, root)


def bootstrap_from_config(root: Path) -> None:
    config_path = root / CONFIG_NAME
    if not config_path.exists():
        raise FileNotFoundError(config_path)

    config = load_json(config_path)
    if not isinstance(config, list):
        raise ValueError(f"{config_path} must contain a JSON array")

    created = 0
    for entry in config:
        if not isinstance(entry, dict):
            continue
        firmware_ref = entry.get("firmware", "")
        parts = Path(firmware_ref).parts
        if len(parts) < 4 or parts[0] != "firmware":
            continue

        version = parts[1]
        board_id = parts[2]
        board_dir = root / "firmware" / version / board_id
        board_dir.mkdir(parents=True, exist_ok=True)

        img_ref = copy_image_to_stable_folder(root, entry.get("img_schematic", ""), board_id)
        metadata = {
            "title": entry.get("title", board_id),
            "board": entry.get("board", ""),
            "display": entry.get("display", ""),
            "img_schematic": img_ref,
            "hotword": entry.get("hotword", DEFAULT_HOTWORD),
        }
        for key, value in entry.items():
            if key not in metadata and key not in {"firmware", "version"}:
                metadata[key] = value

        meta_path = board_dir / METADATA_NAME
        if not meta_path.exists():
            write_json(meta_path, metadata)
            created += 1

    print(f"Bootstrap complete, created {created} metadata file(s).")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update xiaozhi_firmware/config.json from firmware metadata.")
    parser.add_argument("root", nargs="?", default=".", help="xiaozhi_firmware root folder")
    parser.add_argument("--bootstrap-from-config", action="store_true",
                        help="Create firmware.json files and stable images from the existing config.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    if not (root / "firmware").is_dir():
        raise SystemExit(f"Firmware root must contain firmware/: {root}")

    if args.bootstrap_from_config:
        bootstrap_from_config(root)

    entries = build_config(root)
    write_json(root / CONFIG_NAME, entries)
    print(f"Wrote {root / CONFIG_NAME} with {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}.")


if __name__ == "__main__":
    main()
