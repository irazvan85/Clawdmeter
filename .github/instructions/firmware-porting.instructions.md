---
applyTo: "firmware/platformio.ini,firmware/src/**"
description: "Use for firmware board-port work to the ESP32 1.14 ST7789 board while preserving BLE/daemon compatibility and applying the porting checklist."
---

# Firmware Porting Instructions (ESP32 1.14 ST7789)

Use this instruction for firmware migration tasks from the current Waveshare ESP32-S3 AMOLED target to the ESP32 1.14 inch ST7789 board documented in [doc/spec.md](doc/spec.md).

## Required References

- [AGENTS.md](AGENTS.md)
- [CLAUDE.md](CLAUDE.md)
- [doc/spec.md](doc/spec.md)
- [doc/pinlayout.md](doc/pinlayout.md)
- [doc/arduino_ide_samplecode.md](doc/arduino_ide_samplecode.md)

## Porting Checklist

1. Confirm the target board in this setup may currently be running MicroPython firmware; for this project, first flash the repository firmware before evaluating runtime behavior.
2. Keep BLE protocol and daemon contract unchanged unless the user explicitly asks otherwise:
   - service: `4c41555a-4465-7669-6365-000000000001`
   - RX/TX/REQ characteristics in `firmware/src/ble.cpp`
   - payload shape in `firmware/src/data.h`
3. Apply target LCD SPI pins from [doc/spec.md](doc/spec.md): MOSI=23, SCLK=18, CS=15, DC=2, RST=4, BLK=32.
4. Treat PMU/IMU/touch as unavailable on target by default; if stubbing, keep interfaces stable (`power_*`, `imu_*`).
5. Keep edits focused on these migration files unless requested otherwise:
   - `firmware/platformio.ini`
   - `firmware/src/display_cfg.h`
   - `firmware/src/main.cpp`
   - `firmware/src/power.h` and `firmware/src/power.cpp`
   - `firmware/src/imu.h` and `firmware/src/imu.cpp`
   - `firmware/src/ui.h` and `firmware/src/ui.cpp`
6. After each subsystem change, run a compile check (`pio run -d firmware`) before moving to the next subsystem.

## Editing Rules

- Keep changes minimal and avoid unrelated formatting churn.
- Preserve existing module boundaries and naming unless explicitly asked to refactor.
- Link to docs instead of duplicating long hardware explanations in code comments.