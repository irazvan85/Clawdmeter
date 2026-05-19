# ESP32 1.14-inch LCD Board: Details Extracted from Images

This document consolidates the visible technical information from the vendor images in this repository.

## Source Documents
- [Arduino IDE setup steps 1-4](../doc/arduino_ide.md)
- [Arduino IDE setup steps 5-8](../doc/arduino_ide_lib.md)
- [Arduino IDE sample code (step 9)](../doc/arduino_ide_samplecode.md)
- [Board pinout diagram](../doc/pinlayout.md)
- [Board specs and marketing sheet](../doc/spec.md)

## 1) Arduino IDE Setup Flow (from tutorial images)

### Steps 1-4

1. Web Search CH340 Driver
- Instruction shown: Search and download CH340 driver.
- Note shown: Recommended for Win10 OS.
- Search examples shown: Google and Microsoft Bing with query CH340 driver.

2. Add Boards Manager URLs in IDE
- Path shown: IDE -> Preferences -> Additional Boards Manager URLs.
- URL shown in red:

```text
https://dl.espressif.com/dl/package_esp32_index.json
```

3. Install ESP32 Board Package
- Path shown: IDE -> Board -> Boards Manager.
- Search term shown: esp32.
- Package shown in screenshot: esp32 by Espressif Systems.
- Installed version visible in screenshot: 2.0.11 (shown as INSTALLED).

4. Select ESP32 Board
- Path shown: IDE -> Tools -> Board.
- Board selection shown: ESP32 Dev Module.

### Steps 5-8

5. Include Library
- Path shown: IDE -> Sketch -> Include Library -> Manage Libraries.

6. Install ST7789 Library
- Search term shown: Adafruit st7789.
- Library shown: Adafruit ST7735 and ST7789 Library.
- Version shown in screenshot: 1.10.3.

7. Install Dependencies
- Dialog shown indicates missing dependencies for Adafruit ST7735 and ST7789 Library 1.10.3.
- Dependencies shown:
  - Adafruit GFX Library
  - Adafruit seesaw Library
- Prompt shown: install all missing dependencies.

8. Set Board and Processor (Tools menu)
- The screenshot shows these Tool parameters:
  - Board: ESP32 Dev Module
  - Upload Speed: 921600
  - CPU Frequency: 240MHz (WiFi/BT)
  - Flash Frequency: 80MHz
  - Flash Mode: QIO
  - Flash Size: 4MB (32Mb)
  - Partition Scheme: Default 4MB with spiffs (1.2MB APP/1.5MB SPIFFS)
  - Core Debug Level: None
  - PSRAM: Disabled
  - Arduino Runs On: Core 1
  - Events Run On: Core 1
  - Erase All Flash Before Sketch Upload: Disabled
  - JTAG Adapter: Disabled

## 2) Sample Firmware Code (from step 9 image)

Step 9 notes shown:
- Copy code into IDE and upload; text should display on screen.
- MicroPython sample code can be searched online.

Transcribed sample code:

```cpp
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

#define LCD_MOSI 23    // ESP32 D23
#define LCD_SCLK 18    // ESP32 D18
#define LCD_CS   15    // ESP32 D15
#define LCD_DC   2     // ESP32 D2
#define LCD_RST  4     // ESP32 D4
#define LCD_BLK  32    // ESP32 D32

Adafruit_ST7789 lcd = Adafruit_ST7789(LCD_CS, LCD_DC, LCD_RST);

void setup() {
  lcd.init(135, 240);
  lcd.fillScreen(ST77XX_BLACK);
}

void loop() {
  lcd.setTextSize(3);
  lcd.print("Hello,ideaspark");
  delay(100000);
}

// To get the Source Code for the Image display, please visit:
// https://github.com/GJKJ/ESP32114LCD
```

## 3) LCD Pin Mapping and Board Pinout (from pinout + spec images)

### Dedicated LCD wiring (repeated consistently across images)

| LCD Signal | ESP32 Pin |
|---|---|
| MOSI | D23 / GPIO23 |
| SCLK | D18 / GPIO18 |
| CS | D15 / GPIO15 |
| DC | D2 / GPIO2 |
| RST | D4 / GPIO4 |
| BLK | D32 / GPIO32 |

### Right-side header labels in pinout image (top to bottom)

| Header # | Main Label | Alternate labels shown |
|---|---|---|
| 15 | GPIO23 | COPI, VPI_MOSI, LCD MOSI |
| 14 | GPIO22 | SCL |
| 13 | GPIO1 | TX0 |
| 12 | GPIO3 | RX0 |
| 11 | GPIO21 | SDA |
| 10 | GPIO19 | CIPO, VPI_MISO |
| 9 | GPIO18 | SCK, VPI_SCK, LCD SCLK |
| 8 | GPIO5 | SS, VPI_SS |
| 7 | GPIO17 | TX2 |
| 6 | GPIO16 | RX2 |
| 5 | GPIO4 | A10, LCD RST |
| 4 | GPIO2 | A12, LCD DC |
| 3 | GPIO15 | A13, VPI_SS, LCD CS |
| 2 | GND | Ground |
| 1 | 3.3V | Positive supply |

### Left-side header labels in pinout image (top to bottom)

| Header # | Main Label | Alternate labels shown |
|---|---|---|
| 15 | EN | Enable |
| 14 | GPIO36 | A0, RTCIO0, S_VP |
| 13 | GPIO39 | A3, RTCIO3, S_VN |
| 12 | GPIO34 | A6, RTCIO4, VDET_1 |
| 11 | GPIO35 | A7, RTCIO5, VDET_2 |
| 10 | GPIO32 | A4, RTCIO9, 32K_XP, LCD BLK |
| 9 | GPIO33 | A5, RTCIO8, 32K_XN |
| 8 | GPIO25 | A18, DAC1 |
| 7 | GPIO26 | A19, DAC2 |
| 6 | GPIO27 | A17 |
| 5 | GPIO14 | A16 |
| 4 | GPIO12 | A15 |
| 3 | GPIO13 | A14 |
| 2 | GND | Ground |
| 1 | VIN | Input supply |

### Notes shown in the pinout image

- GPIO 34, 35, 36, and 39 are input-only.
- TX0 and RX0 (Serial0) are used for serial programming.
- TX2 and RX2 can be accessed via Serial2.
- DAC means Digital-to-Analog Converter; ADC means Analog-to-Digital Converter.
- Default SPI is VSPI; VSPI and HSPI pins can be reassigned to GPIOs.
- GPIOs support PWM and interrupts.
- Built-in LED is connected to GPIO2.
- Some GPIOs are used by flash memory and may not be exposed.

## 4) Board Specifications and Features (from spec image)

### Main board description highlights

- Board combines ESP32 dev board functionality with integrated 1.14-inch LCD.
- Display is 135x240 full-color IPS with ST7789 driver.
- USB interface/driver shown: CH340 via Type-C board connection.
- Wireless capabilities shown: 2.4GHz Wi-Fi plus BLE dual mode.
- The sheet positions the board for IoT and display-rich embedded applications.

### ESP32 Devkit section (as listed)

- Microcontroller: 32-bit Xtensa dual-core @240MHz
- Operating Voltage: 3.3V
- Driver: CH340
- Wi-Fi: IEEE 802.11 b/g/n 2.4GHz, BLE 4.2 BR/EDR
- Memory line shown: 4MB flash, 520KB SRAM (16KB cache), 448KB ROM
- Peripherals line shown: 34 GPIOs, 4x SPI, 3x UART, 2x I2C
- Additional interfaces line shown: 2x I2S, RMT, LED PWM, 1 host SD/eMMC/SDIO
- Additional controller line shown: 1 slave SDIO/SPI, TWAI, 12-bit ADC, Ethernet
- Onboard USB-TTL based on CH340 included for plug-and-play

### 1.14-inch IPS display section (as listed)

- Interface Type: SPI, 4 line
- Driver Chip: ST7789
- Display Direction: high-definition IPS, adjustable orientation
- Display Color: multicolor
- Number of Pins: 13 pin (welding, 0.7mm pitch)
- View Direction: full view
- Operating Temperature: -20 to 70 degrees C
- Voltage: 3.3V
- Current: 20mA

### Screen parameters section (as listed)

- Resolution: 135(H)RGB x 240(V)
- Display Area: 14.864(H) x 24.912(V) mm
- Panel Size: 17.6(H) x 31.0(V) x 1.6(D) mm
- Pixel Pitch: 0.1101(H) x 0.1038(V) mm
- Backlight Type: 1 White LED Parallel

### Applications list shown

- Network information display
- Internet of Things
- Home automation
- Measurement tools
- Smart home gateway
- Sensor network
- Industrial control
- etc.

### Package list shown

- 1 x ESP32 1.14 inch LCD Board

## 5) Practical Quick Reference from Extracted Data

1. Install CH340 driver first.
2. Add ESP32 board URL in Arduino IDE preferences.
3. Install esp32 board package and select ESP32 Dev Module.
4. Install Adafruit ST7735/ST7789 library and dependencies.
5. Use LCD pins GPIO23, GPIO18, GPIO15, GPIO2, GPIO4, GPIO32.
6. Initialize ST7789 with resolution 135x240.

## 6) Local Connection Note (User Setup)

- Current detected board connection: USB-SERIAL CH340 on COM13.
- Use COM13 as the default upload/serial monitor port for this workstation.
