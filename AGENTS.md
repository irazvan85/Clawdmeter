# AGENTS

Purpose: help AI coding agents be immediately productive when adapting this project from the current Waveshare ESP32-S3-Touch-AMOLED-2.16 target to the ESP32 1.14 inch ST7789 board documented in `doc/`.

## Read First

- Project architecture and known gotchas: [CLAUDE.md](CLAUDE.md)
- Current user-facing behavior and host setup: [README.md](README.md)
- Target board specs (authoritative for migration): [doc/spec.md](doc/spec.md)
- Target board pin map: [doc/pinlayout.md](doc/pinlayout.md)
- Vendor sample wiring/code: [doc/arduino_ide_samplecode.md](doc/arduino_ide_samplecode.md)
- Consolidated extracted notes: [doc/board_details_extracted_from_images.md](doc/board_details_extracted_from_images.md)

## Scope Guardrails

- Only implement work requested by the user.
- For board-port tasks, prioritize firmware changes under `firmware/`.
- Keep BLE protocol and daemon contract stable unless explicitly requested:
  - service `4c41555a-4465-7669-6365-000000000001`
  - RX/TX/REQ characteristics in `firmware/src/ble.cpp`
  - usage payload shape in `firmware/src/data.h`
- Do not duplicate long documentation into code comments or new docs; link to `doc/*.md` and `CLAUDE.md`.

## Current vs Target Hardware (Migration Baseline)

- Current firmware target: ESP32-S3 + CO5300 480x480 AMOLED (QSPI), CST9220 touch, AXP2101 PMU, QMI8658 IMU.
- Target board from `doc/`: ESP32-WROOM-32 + ST7789 135x240 SPI LCD with pins:
  - MOSI=GPIO23, SCLK=GPIO18, CS=GPIO15, DC=GPIO2, RST=GPIO4, BLK=GPIO32.
- Target board is currently running MicroPython firmware in your setup; for project bring-up, replace it by flashing this repository firmware first.
- Assume PMU/IMU/touch are unavailable on the target unless user confirms external modules.

## High-Impact Files for Porting

- Build environment: `firmware/platformio.ini`
- Display and board pin definitions: `firmware/src/display_cfg.h`
- Display bus/driver setup and main loop integration: `firmware/src/main.cpp`
- Power abstraction (AXP2101-coupled today): `firmware/src/power.h`, `firmware/src/power.cpp`
- IMU abstraction (QMI8658-coupled today): `firmware/src/imu.h`, `firmware/src/imu.cpp`
- UI layout/scaling for 135x240: `firmware/src/ui.h`, `firmware/src/ui.cpp`

## Build and Validation

- Preferred build command: `pio run -d firmware`
- Preferred flash command (Linux/macOS scripts may differ by host):
  - `pio run -d firmware -t upload --upload-port <PORT>`
- If UI changes are made, validate visuals using framebuffer screenshot workflow documented in [CLAUDE.md](CLAUDE.md).
- Keep changes minimal and verify compile errors after edits.

## Code Change Conventions

- Preserve existing naming and module boundaries unless refactor is explicitly requested.
- Avoid broad formatting-only diffs.
- When stubbing unavailable hardware for the target board, keep function signatures stable (`power_*`, `imu_*`) to reduce churn.
- Prefer incremental commits-sized changes: compile after each subsystem change (display, then input/power, then UI tuning).

## Suggested Follow-on Customizations

If this repo starts receiving repeated board-port tasks, add:

1. `.github/instructions/firmware-porting.instructions.md` (applyTo: `firmware/src/**`, `firmware/platformio.ini`) with strict porting checklist.
2. `.github/prompts/port-to-st7789.prompt.md` for a repeatable migration workflow.
3. `.github/agents/firmware-migration.agent.md` to run staged migration (display bring-up -> compile -> UI fit).
