#!/bin/bash
# Flash merged firmware file

python -m esptool --chip esp32s3 -b 460800 \
  --before default_reset --after hard_reset \
  write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m \
  0x0 merged_firmware.bin
