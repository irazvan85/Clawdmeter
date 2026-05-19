// Stubbed: AXP2101 PMU not available on ideaspark ESP32 1.14" ST7789 board.
#include "power.h"

void power_init(void)          {}
void power_tick(void)          {}
int  power_battery_pct(void)   { return -1; }
bool power_is_charging(void)   { return false; }
bool power_pwr_pressed(void)   { return false; }
