// Stubbed: QMI8658 IMU not available on ideaspark ESP32 1.14" ST7789 board.
// Auto-rotation is disabled; display stays at rotation 0.
#include "imu.h"

void    imu_init(void)         {}
void    imu_tick(void)         {}
uint8_t imu_get_rotation(void) { return 0; }
