#pragma once
#include "data.h"

// MQ-135 air-quality sensor on an analog pin (ADC1 — ADC2 is unusable while
// WiFi is up). Wiring: module V -> 5V, G -> GND, S -> 10k -> GPIO 34, with a
// second 10k from GPIO 34 to GND. The divider halves the 0-5 V output so the
// pin never sees more than 2.5 V; GAS_DIVIDER undoes it in software.
//
// The MQ-135 is one heated SnO2 element: every reducing gas lowers the same
// resistance, so it yields one number -- Rs/R0, resistance now relative to a
// clean-air baseline. That ratio drives the headline level. The per-gas
// figures are the datasheet curves applied to that one ratio ("if this gas
// alone caused the drop"), so they rise and fall together by construction.
//
// Baseline (R0): until `gascal` is run in fresh air, R0 auto-tracks the
// cleanest reading seen (like a CO2 sensor's automatic baseline correction),
// so the screen is usable straight away. `gascal` pins it; `gasauto` reverts.
// Persisted in NVS namespace "gas".

#define GAS_PIN      34
#define GAS_DIVIDER  2.0f   // two equal resistors; set to 1.0f if S is wired direct

// One datasheet curve: ppm = a * (Rs/R0_ds)^b, fitted by MQSensorsLib to the
// MQ-135 datasheet's Fig. 3, where R0_ds is defined so clean air reads 3.6.
struct GasDef {
    const char* key;       // JSON key in /api/state's air.gases
    const char* name;      // on-screen label
    float a, b;
    float base;            // ambient level added back (CO2's ~400 ppm outdoors)
    float lo, hi;          // datasheet's plotted range (excess ppm)
    float caution, alarm;  // total ppm; see GAS_DEFS[] for where each comes from
};
extern const GasDef GAS_DEFS[AIR_GAS_COUNT];

void gas_sensor_init(void);
void gas_sensor_tick(void);           // call from loop(); samples once a second
bool gas_sensor_get(AirData* out);    // false until the first sample is taken

// Setup / QA helpers (serial commands, the Air long-press, POST /api/gas).
void gas_sensor_print(void);          // raw mV, Rs/RL, R0, ratio + every gas equivalent
// Pin R0 to the current reading -- run in fresh air, after burn-in. Entry
// points: serial `gascal`, long-press on the Air screen, POST /api/gas.
// allow_warming: the serial path passes true, because opening the port resets
// the ESP32 (restarting the warm-up clock) without cutting the heater's 5V.
// The button/HTTP paths pass false -- for them "warming" means a real cold start.
enum GasCalResult { GAS_CAL_OK, GAS_CAL_NO_SENSOR, GAS_CAL_WARMING };
GasCalResult gas_sensor_calibrate(bool allow_warming);
void gas_sensor_auto(void);           // drop the pinned R0, back to auto-tracking
