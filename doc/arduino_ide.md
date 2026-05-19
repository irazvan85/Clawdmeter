# Get Started with Arduino IDE — Steps 1–4

Set up your ESP32 1.14 inch LCD board with Arduino IDE.

---

## Step 1 — Web Search CH340 Driver

Search for and download the CH340 driver. Recommended for Windows 10 OS.

- Search "CH340 driver" on Google.com or Microsoft Bing.
- Download and install the driver before connecting the board.

---

## Step 2 — Add Boards Manager URL in IDE

Open Arduino IDE and navigate to:

> **IDE → Preferences → "Additional Boards Manager URLs"**

Add the following URL:

```
https://dl.espressif.com/dl/package_esp32_index.json
```

Click **OK**.

---

## Step 3 — Install ESP32 Board Package

> **IDE → "Board" → "Boards Manager"**

1. In the search box, type `esp32`.
2. Find the package **"esp32" by Espressif Systems** (version 2.0.11 or later).
3. Click **Install**.

The following boards are included in this package:
- ESP32 Dev Board
- ESP32-S2 Dev Board
- ESP32-S3 Dev Board
- ESP32-C3 Dev Board

---

## Step 4 — Select ESP32 Board

> **IDE → "Tools" → "Board: ESP32 Dev Module"**

Recommended board settings:

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

---

Continue to [arduino_ide_lib.md](arduino_ide_lib.md) for steps 5–8 (library installation).
