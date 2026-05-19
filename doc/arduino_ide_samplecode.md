# Get Started with Arduino IDE — Step 9: Sample Code

Copy the code below into the Arduino IDE and upload. You will see text displayed on the screen.

> MicroPython sample code can be searched online.  
> For image display source code, visit: https://github.com/GJKJ/ESP32114LCD

---

## Sample Sketch

```cpp
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

#define LCD_MOSI 23   // ESP32 D23
#define LCD_SCLK 18   // ESP32 D18
#define LCD_CS   15   // ESP32 D15
#define LCD_DC    2   // ESP32 D2
#define LCD_RST   4   // ESP32 D4
#define LCD_BLK  32   // ESP32 D32

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
```

---

## Notes

- The sketch uses hardware SPI (MOSI=23, SCLK=18) with CS=15, DC=2, RST=4.
- Backlight (BLK) on GPIO32 — set `pinMode(LCD_BLK, OUTPUT); digitalWrite(LCD_BLK, HIGH);` in `setup()` to turn it on.
- Display resolution: 135×240. Pass these values to `lcd.init(135, 240)`.
- `ST77XX_BLACK` and other color constants are defined in the Adafruit ST7789 library.

---

## Required Libraries

| Library | Source |
|---------|--------|
| Adafruit GFX Library | Arduino Library Manager |
| Adafruit ST7735 and ST7789 Library | Arduino Library Manager |
| Adafruit BusIO | Installed automatically as dependency |

See [arduino_ide_lib.md](arduino_ide_lib.md) for installation steps.
