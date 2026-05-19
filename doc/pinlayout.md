# ideaspark ESP32 1.14 inch TFT LCD Display Board — Pinout

## Pin Legend

| Color | Category |
|-------|----------|
| Gray | Physical Pin |
| Green | Control Pins |
| Teal | GPIO Pins |
| Red | Positive Supply |
| Black | Ground Supply |
| Yellow | DAC Outputs |
| Pink | I2C Pins |
| Blue | SPI Pins |
| Orange | UART Pins |
| Dark | Excluded Pins |
| Purple | ADC Inputs |
| Cyan | Other Related Functions |

---

## LCD Signal Pins (right side, highlighted)

| GPIO | Signal | Notes |
|------|--------|-------|
| GPIO23 | **MOSI** | SPI VSPI_MOSI — LCD data |
| GPIO18 | **SCLK** | SPI VSPI_SCK — LCD clock |
| GPIO15 | **CS** | SPI VSPI_SS — LCD chip select |
| GPIO2 | **DC** | LCD data/command |
| GPIO4 | **RST** | LCD reset |
| GPIO32 | **BLK** | LCD backlight (32K_XP / RTCIO9) |

---

## Full Pin Map

### Right Side (top → bottom)

| Physical | GPIO | Alt Functions | LCD Signal |
|----------|------|---------------|-----------|
| 15 | GPIO23 | COPI, VSPI_MOSI | **MOSI** |
| 14 | GPIO22 | SCL | — |
| 13 | GPIO1 | TX0 | — |
| 12 | GPIO3 | RX0 | — |
| 11 | GPIO21 | SDA | — |
| 10 | GPIO19 | CIPD, VSPI_MISO | — |
| 9 | GPIO18 | SCK, VSPI_SCK | **SCLK** |
| 8 | GPIO5 | CS, VSPI_SS | — |
| 7 | GPIO17 | TX2 | — |
| 6 | GPIO16 | RX2 | — |
| 5 | GPIO4 | A18 | **RST** |
| 4 | GPIO2 | A12 | **DC** |
| 3 | GPIO15 | A13, HSPI_SS | **CS** |
| 2 | GND | — | — |
| 1 | 3.3V | — | — |

### Left Side (top → bottom)

| Physical | GPIO | Alt Functions | Notes |
|----------|------|---------------|-------|
| 15 | ENABLE | EN | Enable pin |
| 14 | RTCIO8 (A0) | GPIX36 | Input only |
| 13 | RTCIO3 (A3) | GPIX39 | Input only |
| 12 | RTCIO4 (A6) | GPIX34 | Input only |
| 11 | RTCIO5 (A7) | GPIX35 | Input only |
| 10 | RTCIO9 (A4) | GPIO32 | 32K_XP — **LCD BLK** |
| 9 | RTCIO8 (A5) | GPIO33 | 32K_XN |
| 8 | RTCIO6 (A18) | GPIO25 | DAC1 |
| 7 | RTCIO7 (A17) | GPIO26 | DAC2 |
| 6 | RTCIO17 (A16) | GPIO27 | — |
| 5 | RTCIO16 (A15) | GPIO14 | HSPI_SCK |
| 4 | RTCIO15 (A14) | GPIO13 | HSPI_MOSI |
| 3 | — | GPIO13 | D13 |
| 2 | GND | — | — |
| 1 | VIN | — | Power input |

---

## Important Notes

- **GPIO34–GPIO39 are input-only.** They cannot be used as outputs.
- **TX0 and RX0 (Serial0)** are used for USB serial programming.
- **TX2 and RX2** can be accessed as Serial2.
- **DAC**: Digital-to-Analog Converter. ADC inputs are Analog-to-Digital Converter.
- Default SPI is VSPI. Both VSPI and HSPI pins can be set to any GPIO pins.
- All GPIO pins support PWM and interrupts.
- Built-in LED is connected to GPIO2 (shared with LCD DC — use with care).
- Some GPIO pins are used for interfacing flash memory and are not shown.
- IDEASPARK ESP32 Board pin names and functions are the same as "ESP32 DEVKIT V1".
