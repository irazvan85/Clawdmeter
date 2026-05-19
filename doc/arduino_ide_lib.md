# Get Started with Arduino IDE — Steps 5–8

Continuation from [arduino_ide.md](arduino_ide.md) (steps 1–4).

---

## Step 5 — Open Library Manager

> **IDE → "Sketch" → "Include Library" → "Manage Libraries..."**

---

## Step 6 — Search for ST7789 Library

In the Library Manager search box, type: `Adafruit st7789`

Find and select: **"Adafruit ST7735 and ST7789 Library" by Adafruit**

> This is a library for the Adafruit ST7735 and ST7789 SPI displays.

Click **Install** (version 1.10.3 or later).

---

## Step 7 — Install All Dependencies

After clicking Install, a dialog will appear:

> "The library Adafruit ST7735 and ST7789 Library needs some other library dependencies currently not installed:"
> - **Adafruit GFX Library**
> - **Adafruit seesaw Library**
> 
> "Would you like to install also all the missing dependencies?"

Click **"Install all"** to install:
- Adafruit ST7735 and ST7789 Library
- Adafruit GFX Library
- Adafruit BusIO (pulled in automatically)

---

## Step 8 — Set Board and Processor

Confirm Tools settings match the following (same as Step 4):

| Setting | Value |
|---------|-------|
| Board | ESP32 Dev Module |
| Upload Speed | 921600 |
| CPU Frequency | 240MHz (WiFi/BT) |
| Flash Frequency | 80MHz |
| Flash Mode | QIO |
| Flash Size | 4MB (32Mb) |
| Partition Scheme | Default 4MB with spiffs (1.2MB APP/1.5MB SPIFFS) |
| Core Debug Level | None |
| PSRAM | Disabled |
| Arduino Runs On | Core 1 |
| Events Run On | Core 1 |
| JTAG Adapter | Disabled |
| Port | COM13 (or your CH340 port) |

---

Continue to [arduino_ide_samplecode.md](arduino_ide_samplecode.md) for the sample sketch.
