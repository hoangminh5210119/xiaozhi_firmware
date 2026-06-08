# xiaozhi_firmware

Firmware files served by the update server.

## Folder layout

```text
config.json
images/<board_id>/<image_file>
firmware/<version>/<board_id>/merged_firmware.bin
firmware/<version>/<board_id>/firmware.json
```

Images are kept outside version folders so new firmware versions can reuse the
same schematic image paths.

## After building firmware

Run from the Xiaozhi firmware source root, after `idf.py build`:

```bash
python3 merge_and_copy_firmware.py \
  /Users/dominh/Desktop/AI_CODE/xiaozhi_firmware \
  --update-json
```

The script creates/copies:

- `build/merged_firmware.bin`
- `firmware/<version>/<auto_board_id>/merged_firmware.bin`
- `firmware/<version>/<auto_board_id>/firmware.json`
- refreshed `config.json` when `--update-json` is provided

`title`, `board`, `display`, `hotword`, and folder name are detected from the
firmware source `sdkconfig` and build metadata.

Folder creation logic:

1. Read firmware version from `build/project_description.json`.
2. If `firmware/<version>/` does not exist, create it.
3. Build device name from chip/camera + display driver + display size.
   Example: `esp32s3_ssd1306_128x64`, `esp32s3camera_st7789_240x320`.
4. If `firmware/<version>/<device>/` does not exist, create it.
5. Merge and copy `merged_firmware.bin` into that device folder.

The generated `firmware.json` keeps clear source details:

```json
{
  "board": "esp32s3",
  "chip": "esp32s3",
  "display_driver": "ssd1306",
  "display_size": "128x64",
  "board_symbol": "BOARD_TYPE_BREAD_COMPACT_WIFI",
  "display_symbol": "OLED_SSD1306_128X64"
}
```

## Refresh JSON only

Run from this folder:

```bash
python3 update_json.py
```
