#pragma once
// Signal-quality check for the MQ-135's raw output, fed one sample a second
// by gas_sensor.cpp. A loose S/GND/5V connection makes the pin flick between
// the ADC floor and the real value; on 2026-10-29 one such dropout became the
// auto baseline (R0) and every later reading showed "Bad". Baseline updates,
// calibration and history only trust the sensor while this says GAS_SIG_OK.
//
// Deliberately Arduino-free: tools/tests/test_gas_signal.py builds it with the
// host compiler.
#include <stdint.h>

#define GAS_SIG_WINDOW        30      // samples (1 Hz -> last 30 s)
#define GAS_SIG_ABS_MV        150     // allowed max-min spread, S mV
#define GAS_SIG_REL           0.10f   // ...or this fraction of the median, whichever is larger
#define GAS_SIG_FLOOR_PIN_MV  160     // raw pin reading at/below this = ADC floor (~142 mV at 0 V)

enum GasSignalState { GAS_SIG_OK, GAS_SIG_UNSTABLE, GAS_SIG_FLOOR };

struct GasSignal {
    uint16_t mv[GAS_SIG_WINDOW];   // S mV (divider undone), un-smoothed
    uint8_t  head;
    uint8_t  count;
    uint16_t last_pin_mv;
};

void           gas_signal_reset(GasSignal* s);
void           gas_signal_push(GasSignal* s, float s_mv, int pin_mv);  // one raw sample
GasSignalState gas_signal_state(const GasSignal* s);                   // FLOOR > UNSTABLE > OK
