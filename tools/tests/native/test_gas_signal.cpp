// Host test for firmware/src/gas_signal.{h,cpp}; built and run by
// tools/tests/test_gas_signal.py. Exit code = number of failed checks.
#include <stdio.h>
#include "gas_signal.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); failures++; } } while (0)

static void fill(GasSignal* s, float mv, int n, int pin) {
    for (int i = 0; i < n; i++) gas_signal_push(s, mv, pin);
}

static void empty_is_unstable() {
    GasSignal s; gas_signal_reset(&s);
    CHECK(gas_signal_state(&s) == GAS_SIG_UNSTABLE);
}

static void partial_window_is_unstable() {
    GasSignal s; gas_signal_reset(&s);
    fill(&s, 1000, GAS_SIG_WINDOW - 1, 500);
    CHECK(gas_signal_state(&s) == GAS_SIG_UNSTABLE);
}

static void steady_is_ok() {
    GasSignal s; gas_signal_reset(&s);
    for (int i = 0; i < GAS_SIG_WINDOW; i++) gas_signal_push(&s, i % 2 ? 1010 : 990, 500);
    CHECK(gas_signal_state(&s) == GAS_SIG_OK);
}

static void slow_drift_is_stable() {
    GasSignal s; gas_signal_reset(&s);
    for (int i = 0; i < GAS_SIG_WINDOW; i++)
        gas_signal_push(&s, 1000 + 100.0f * i / (GAS_SIG_WINDOW - 1), 550);
    CHECK(gas_signal_state(&s) == GAS_SIG_OK);
}

static void relative_threshold_applies() {
    GasSignal s; gas_signal_reset(&s);
    for (int i = 0; i < GAS_SIG_WINDOW; i++) gas_signal_push(&s, i % 2 ? 3250 : 3000, 1500);
    CHECK(gas_signal_state(&s) == GAS_SIG_OK);
}

static void dropout_pattern_is_unstable() {
    // S mV seen on 2026-10-29 with a loose MQ-135 connection.
    static const float LOG[] = { 2348, 2979, 2320, 3361, 2201, 1061, 3285 };
    GasSignal s; gas_signal_reset(&s);
    for (int i = 0; i < GAS_SIG_WINDOW; i++) gas_signal_push(&s, LOG[i % 7], 1200);
    CHECK(gas_signal_state(&s) == GAS_SIG_UNSTABLE);
}

static void floor_wins_over_stable() {
    GasSignal s; gas_signal_reset(&s);
    fill(&s, 284, GAS_SIG_WINDOW, 142);
    CHECK(gas_signal_state(&s) == GAS_SIG_FLOOR);
}

static void floor_only_reflects_latest_pin() {
    GasSignal s; gas_signal_reset(&s);
    fill(&s, 1000, GAS_SIG_WINDOW - 1, 500);
    gas_signal_push(&s, 1000, 142);
    CHECK(gas_signal_state(&s) == GAS_SIG_FLOOR);
    gas_signal_push(&s, 1000, 500);
    CHECK(gas_signal_state(&s) != GAS_SIG_FLOOR);
}

static void recovers_after_glitch_leaves_window() {
    GasSignal s; gas_signal_reset(&s);
    fill(&s, 1000, GAS_SIG_WINDOW, 500);
    gas_signal_push(&s, 300, 150);
    CHECK(gas_signal_state(&s) == GAS_SIG_FLOOR);
    gas_signal_push(&s, 1000, 500);
    CHECK(gas_signal_state(&s) == GAS_SIG_UNSTABLE);
    fill(&s, 1000, GAS_SIG_WINDOW - 1, 500);
    CHECK(gas_signal_state(&s) == GAS_SIG_OK);
}

static void rail_steady_is_ok() {
    GasSignal s; gas_signal_reset(&s);
    fill(&s, 4950, GAS_SIG_WINDOW, 2475);
    CHECK(gas_signal_state(&s) == GAS_SIG_OK);
}

int main() {
    empty_is_unstable();
    partial_window_is_unstable();
    steady_is_ok();
    slow_drift_is_stable();
    relative_threshold_applies();
    dropout_pattern_is_unstable();
    floor_wins_over_stable();
    floor_only_reflects_latest_pin();
    recovers_after_glitch_leaves_window();
    rail_steady_is_ok();
    printf("%d failure(s)\n", failures);
    return failures;
}
