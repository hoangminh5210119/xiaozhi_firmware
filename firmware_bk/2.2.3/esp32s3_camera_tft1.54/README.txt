ESP32-S3 Firmware Flash Instructions
==================================================

Option 1: Flash individual files
--------------------------------------------------
./flash.sh

Option 2: Flash merged firmware (faster)
--------------------------------------------------
./flash_merged.sh

Files included:
  - bootloader.bin (offset: 0x0)
  - partition-table.bin (offset: 0x8000)
  - ota_data_initial.bin (offset: 0xd000)
  - xiaozhi.bin (offset: 0x20000)
  - generated_assets.bin (offset: 0x800000)
  - merged_firmware.bin (complete firmware image)
