# ESP32 1.14 inch LCD Board — Specifications

## Overview

The ESP32 1.14" LCD board has all the features of the traditional ESP32 Devkit V1 module, with the same exact peripheral ports, offers seamless integration with a 1.14-inch LCD display, eliminating the need for frustrating wires and breadboards. Display features a high-resolution 135×240 full color with ST7789 driver and is compatible with I2C interfaces. It uses Type-C USB cable to connect.

The board is based on ESP32-WROOM-32 module integrated with antenna switches, RF Balun, power amplifiers, low-noise amplifiers, filters, and management modules. The entire solution occupies the least area of PCB. 2.4 GHz Wi-Fi plus BLE dual-mode chip, T5MC Ultra-low power consumption 40nm technology, power dissipation performance and RF performance is the best, safe and reliable.

Board uses SPI to connect LCD: D23/GPIO23→MOSI, D18/GPIO18→SCLK, D15/GPIO15→CS, D2/GPIO2→DC, D4/GPIO4→RST, D32/GPIO32→BLK.

To install the CH340 driver, search for "CH340 Driver" on Google.com or Bing.com and follow the installation instructions provided. Recommended for Win10 Operating System.

This board is an outstanding option for various Internet of Things (IoT) projects: Internet Weather Stations, Graphic Plotter, Data Monitor, and other similar applications.

---

## ESP32 Devkit — Specifications & Features

| Feature | Detail |
|---------|--------|
| Microcontroller | 32-bit Xtensa dual-core @ 240 MHz |
| Operating Voltage | 3.3V |
| Driver | CH340 |
| Wi-Fi | IEEE 802.11 b/g/n 2.4GHz |
| Bluetooth | BLE 4.2 BR/EDR |
| Flash | 4 MB, 520 KB SRAM (16 KB for cache), 448 KB ROM |
| GPIOs | 34 total |
| SPI | 4x |
| UART | 3x |
| ADC | 12-bit |
| I2C | 2x |
| Other | I2S, RMT, LED PWM, 1 host SD/eMMC/SDIO, 1 slave SDIO/SPI, TWAI, Ethernet |
| USB-TTL | CH340 onboard (Plug and Play) |

### Applications
- Network information display
- Internet of Things
- Home automation
- Measurement Tools
- Smart home gateway
- Sensor Network
- Industrial Control

---

## 1.14 inch IPS Multicolor TFT LCD

| Feature | Detail |
|---------|--------|
| Interface | SPI, 4-line |
| Driver Chip | ST7789 |
| Display Direction | High-definition IPS, adjustable |
| Colors | Multicolor |
| Pins | 13 pin (welding, 0.7mm pitch) |
| View Direction | Full View |
| Operating Temperature | -20 to 70°C |
| Voltage | 3.3V |
| Current | 20mA |

### Screen Parameters
| Parameter | Value |
|-----------|-------|
| Resolution | 135(H) × 240(V) |
| Display Area | 14.864(H) × 24.912(V) mm |
| Panel Size | 17.6(H) × 31.0(V) × 1.6(D) mm |
| Pixel Pitch | 0.1101(H) × 0.1038(V) mm |
| Backlight | 1 White LED Parallel |

---

## ESP32 and LCD Port Mapping

| ESP32 Pin | LCD Signal |
|-----------|-----------|
| VCC (3.3V) | VCC |
| GND | GND |
| D2 (GPIO2) | DC |
| D4 (GPIO4) | RST |
| D15 (GPIO15) | CS |
| D18 (GPIO18) | SCLK |
| D23 (GPIO23) | MOSI |
| D32 (GPIO32) | BLK |

---

## Package List
- 1× ESP32 1.14 inch LCD Board

---

## How to Make the Board Work

1. Download and install the CH340 driver.
2. Connect the board to the computer with a Type-C USB cable.
3. Configure the Arduino IDE (see [arduino_ide.md](arduino_ide.md) and [arduino_ide_lib.md](arduino_ide_lib.md)).
4. Upload sample code (see [arduino_ide_samplecode.md](arduino_ide_samplecode.md)).
