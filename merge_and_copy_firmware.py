#!/usr/bin/env python3
"""
Merge ESP32-S3 firmware files into one image, copy it to xiaozhi_firmware,
and create per-board metadata for update_json.py.

Run from the firmware source root after `idf.py build`:
  python3 merge_and_copy_firmware.py /Users/dominh/Desktop/AI_CODE/xiaozhi_firmware --update-json

The script reads sdkconfig/build metadata and automatically creates:
  firmware/<version>/<board_id>/merged_firmware.bin
  firmware/<version>/<board_id>/firmware.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any


CHIP = "esp32s3"
FLASH_SIZE = 16 * 1024 * 1024
MERGED_NAME = "merged_firmware.bin"
METADATA_NAME = "firmware.json"

FLASH_FILES = [
    (0x0, "build/bootloader/bootloader.bin"),
    (0x8000, "build/partition_table/partition-table.bin"),
    (0xD000, "build/ota_data_initial.bin"),
    (0x20000, "build/xiaozhi.bin"),
    (0x800000, "build/generated_assets.bin"),
]

DISPLAY_CONFIG_PREFIXES = (
    "OLED_",
    "LCD_",
    "AUDIO_BOARD_LCD_",
    "ESP32S3_KORVO2_V3_LCD_",
    "BSP_LCD_SIZE_",
)

DISPLAY_NAME_OVERRIDES = {
    "OLED_SSD1306_128X32": "SSD1306 128x32",
    "OLED_SSD1306_128X64": "SSD1306 128x64",
    "OLED_SH1106_128X64": "SH1106 128x64",
}


def load_project_version() -> str:
    desc = Path("build/project_description.json")
    if not desc.exists():
        return ""
    try:
        data = json.loads(desc.read_text(encoding="utf-8"))
        return str(data.get("project_version") or "")
    except Exception:
        return ""


def read_sdkconfig() -> dict[str, str]:
    path = Path("sdkconfig")
    if not path.exists():
        raise SystemExit("Error: sdkconfig not found. Run idf.py build/menuconfig first.")
    config: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        config[key] = value
    return config


def read_kconfig_labels() -> dict[str, str]:
    path = Path("main") / "Kconfig.projbuild"
    labels: dict[str, str] = {}
    if not path.exists():
        return labels

    current = ""
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw.strip()
        if stripped.startswith("config "):
            current = stripped.split(None, 1)[1]
            continue
        if current and stripped.startswith("bool "):
            match = re.search(r'"([^"]+)"', stripped)
            if match:
                labels[current] = match.group(1)
            current = ""
    return labels


def humanize_symbol(symbol: str) -> str:
    text = symbol
    for prefix in ("CONFIG_", "BOARD_TYPE_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.replace("_", " ").title()


def normalize_display_label(label: str) -> str:
    label = re.sub(r",.*$", "", label)
    label = label.replace("*", "x")
    label = re.sub(r"\s+", " ", label).strip()
    return label


def active_board_symbol(config: dict[str, str]) -> str:
    active = sorted(k for k, v in config.items() if k.startswith("CONFIG_BOARD_TYPE_") and v == "y")
    if not active:
        return ""
    return active[0].removeprefix("CONFIG_")


def active_display_symbol(config: dict[str, str]) -> str:
    candidates = []
    for key, value in config.items():
        if value != "y" or not key.startswith("CONFIG_"):
            continue
        symbol = key.removeprefix("CONFIG_")
        if symbol in DISPLAY_NAME_OVERRIDES or symbol.startswith(DISPLAY_CONFIG_PREFIXES):
            candidates.append(symbol)
    return sorted(candidates)[0] if candidates else ""


def active_hotword(config: dict[str, str]) -> str:
    if config.get("CONFIG_USE_CUSTOM_WAKE_WORD") == "y":
        return config.get("CONFIG_CUSTOM_WAKE_WORD_DISPLAY") or config.get("CONFIG_CUSTOM_WAKE_WORD") or "custom"
    if config.get("CONFIG_WAKE_WORD_DISABLED") == "y":
        return ""
    # Current Xiaozhi AFE/ESP wakeword builds commonly package Alexa in assets.
    return "alexa"


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "_", ascii_text)
    return ascii_text.strip("_") or "firmware"


def detect_board_family(target: str, board_symbol: str, board_label: str) -> str:
    text = f"{board_symbol} {board_label}".lower()
    chip = target.lower().replace("-", "")
    if "camera" in text or re.search(r"(^|_)cam($|_)", text):
        return f"{chip}camera"
    return chip


def board_display_name(board_family: str) -> str:
    match = re.match(r"esp32([a-z0-9]*)(camera)?$", board_family)
    if match:
        suffix = match.group(1) or ""
        camera = match.group(2) or ""
        parts = ["Esp32"]
        if suffix:
            parts.append(suffix.upper())
        if camera:
            parts.append("Camera")
        return " ".join(parts)
    return board_family


def parse_display_parts(display_symbol: str, display_label: str) -> tuple[str, str]:
    driver = ""
    size = ""

    match = re.search(r"(SSD1306|SH1106|ST7789|ST7735|ST7796|ILI9341|GC9A01|NV3023|CO5300|SPD2010|ST7701|ST77916)", display_label, re.I)
    if match:
        driver = match.group(1).lower()
    else:
        symbol_match = re.search(r"(SSD1306|SH1106|ST7789|ST7735|ST7796|ILI9341|GC9A01|NV3023|CO5300|SPD2010|ST7701|ST77916)", display_symbol, re.I)
        if symbol_match:
            driver = symbol_match.group(1).lower()

    size_match = re.search(r"(\d+)\s*x\s*(\d+)", display_label, re.I)
    if size_match:
        size = f"{size_match.group(1)}x{size_match.group(2)}"
    else:
        symbol_size = re.search(r"(\d+)X(\d+)", display_symbol)
        if symbol_size:
            size = f"{symbol_size.group(1)}x{symbol_size.group(2)}"

    if not driver:
        driver = slugify(display_label or display_symbol)
    if not size:
        inch_match = re.search(r"(\d+(?:_\d+)?)INCH", display_symbol)
        if inch_match:
            size = inch_match.group(1).replace("_", ".") + "inch"
    return driver, size


def detect_firmware_metadata() -> dict[str, str]:
    config = read_sdkconfig()
    labels = read_kconfig_labels()
    desc = {}
    desc_path = Path("build") / "project_description.json"
    if desc_path.exists():
        try:
            desc = json.loads(desc_path.read_text(encoding="utf-8"))
        except Exception:
            desc = {}

    board_symbol = active_board_symbol(config)
    display_symbol = active_display_symbol(config)
    board_label = labels.get(board_symbol) or humanize_symbol(board_symbol) or str(desc.get("target") or CHIP)
    display_label = DISPLAY_NAME_OVERRIDES.get(display_symbol) or labels.get(display_symbol) or humanize_symbol(display_symbol)
    display_label = normalize_display_label(display_label)
    target = str(desc.get("target") or CHIP)

    chip = target.lower().replace("-", "")
    board_family = detect_board_family(target, board_symbol, board_label)
    board_name = board_display_name(board_family)
    display_driver, display_size = parse_display_parts(display_symbol, display_label)

    device_parts = [board_family]
    if display_driver:
        device_parts.append(display_driver)
    if display_size:
        device_parts.append(display_size)
    board_id = slugify("_".join(device_parts))

    title = f"{board_name} {display_label}".strip()
    image_name = "image.png" if "camera" in board_family else "connect.png"
    image = f"images/{board_id}/{image_name}"
    return {
        "title": title,
        "board": board_name,
        "board_label": board_label,
        "chip": chip,
        "display": display_label,
        "display_driver": display_driver,
        "display_size": display_size,
        "board_symbol": board_symbol,
        "display_symbol": display_symbol,
        "hotword": active_hotword(config),
        "board_id": board_id,
        "img_schematic": image,
    }


def merge_firmware_files(output_file: Path = Path("build") / MERGED_NAME) -> Path:
    print(f"Creating merged firmware file: {output_file}")
    merged_data = bytearray([0xFF] * FLASH_SIZE)

    for offset, filepath in FLASH_FILES:
        src = Path(filepath)
        if not src.exists():
            print(f"Warning: file not found: {filepath}")
            continue

        data = src.read_bytes()
        if offset + len(data) > FLASH_SIZE:
            raise SystemExit(f"Error: {filepath} does not fit at offset 0x{offset:x}")

        merged_data[offset:offset + len(data)] = data
        print(f"  added {filepath} at 0x{offset:x} ({len(data)} bytes)")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(merged_data)
    print(f"Created {output_file} ({len(merged_data)} bytes)")
    return output_file


def read_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_metadata(dest_folder: Path, detected: dict[str, str]) -> None:
    meta_path = dest_folder / METADATA_NAME
    metadata = read_metadata(meta_path)
    metadata = {
        "title": detected["title"],
        "board": detected["board"],
        "display": detected["display"],
        "img_schematic": metadata.get("img_schematic") or detected["img_schematic"],
        "hotword": detected["hotword"],
    }

    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {meta_path.name}")


def create_flash_merged_script(dest_folder: Path) -> None:
    script = dest_folder / "flash_merged.sh"
    script.write_text(
        "#!/bin/bash\n"
        "# Flash merged firmware file\n\n"
        f"python -m esptool --chip {CHIP} -b 460800 \\\n"
        "  --before default_reset --after hard_reset \\\n"
        "  write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m \\\n"
        f"  0x0 {MERGED_NAME}\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o755)
    print("  wrote flash_merged.sh")


def copy_to_destination(merged_file: Path, dest_folder: Path, args: argparse.Namespace, detected: dict[str, str]) -> None:
    dest_folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(merged_file, dest_folder / MERGED_NAME)
    print(f"Copied {MERGED_NAME} to {dest_folder}")

    if args.copy_parts:
        for _, filepath in FLASH_FILES:
            src = Path(filepath)
            if src.exists():
                shutil.copy2(src, dest_folder / src.name)
                print(f"  copied {src.name}")

    create_flash_merged_script(dest_folder)
    write_metadata(dest_folder, detected)


def maybe_update_config(root: Path | None) -> None:
    if root is None:
        return
    script = root / "update_json.py"
    if not script.exists():
        raise SystemExit(f"update_json.py not found: {script}")
    subprocess.run([sys.executable, str(script), str(root)], check=True)


def resolve_firmware_root(path_text: str) -> tuple[Path, Path]:
    path = Path(path_text).expanduser().resolve()
    if path.name == "firmware":
        root = path.parent
        firmware_dir = path
    elif (path / "firmware").is_dir() or not path.suffix:
        root = path
        firmware_dir = path / "firmware"
    else:
        raise SystemExit(f"Destination must be xiaozhi_firmware root or firmware folder: {path}")
    firmware_dir.mkdir(parents=True, exist_ok=True)
    return root, firmware_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge firmware and copy one server-ready bin file.")
    parser.add_argument("firmware_root", help="xiaozhi_firmware root folder or its firmware/ folder")
    parser.add_argument("--copy-parts", action="store_true", help="Also copy individual bin files for manual flashing")
    parser.add_argument("--update-json", action="store_true", help="Run update_json.py after copying")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not Path("build").is_dir():
        raise SystemExit("Error: build/ not found. Run idf.py build first.")

    project_version = load_project_version() or "unknown"
    detected = detect_firmware_metadata()
    root, firmware_dir = resolve_firmware_root(args.firmware_root)
    dest_folder = firmware_dir / project_version / detected["board_id"]

    print("=" * 60)
    print("ESP32-S3 Firmware Merger")
    print("=" * 60)
    print(f"Detected title: {detected['title']}")
    print(f"Detected board_id: {detected['board_id']}")
    print(f"Destination: {dest_folder}")
    merged_file = merge_firmware_files()
    copy_to_destination(merged_file, dest_folder, args, detected)
    maybe_update_config(root if args.update_json else None)
    print("Done.")


if __name__ == "__main__":
    main()
