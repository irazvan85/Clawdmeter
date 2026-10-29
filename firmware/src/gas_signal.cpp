#include "gas_signal.h"
#include <algorithm>
#include <string.h>

void gas_signal_reset(GasSignal* s) {
    memset(s, 0, sizeof(*s));
}

static uint16_t clamp_u16(float v) {
    if (!(v > 0)) return 0;          // also catches NaN
    return v >= 65535.0f ? 65535 : (uint16_t)v;
}

void gas_signal_push(GasSignal* s, float s_mv, int pin_mv) {
    s->mv[s->head] = clamp_u16(s_mv);
    s->head = (uint8_t)((s->head + 1) % GAS_SIG_WINDOW);
    if (s->count < GAS_SIG_WINDOW) s->count++;
    s->last_pin_mv = clamp_u16((float)pin_mv);
}

GasSignalState gas_signal_state(const GasSignal* s) {
    if (s->count > 0 && s->last_pin_mv <= GAS_SIG_FLOOR_PIN_MV) return GAS_SIG_FLOOR;
    if (s->count < GAS_SIG_WINDOW) return GAS_SIG_UNSTABLE;

    uint16_t w[GAS_SIG_WINDOW];
    memcpy(w, s->mv, sizeof(w));
    uint16_t lo = *std::min_element(w, w + GAS_SIG_WINDOW);
    uint16_t hi = *std::max_element(w, w + GAS_SIG_WINDOW);
    std::nth_element(w, w + GAS_SIG_WINDOW / 2, w + GAS_SIG_WINDOW);
    float allowed = std::max((float)GAS_SIG_ABS_MV, GAS_SIG_REL * w[GAS_SIG_WINDOW / 2]);
    return (hi - lo) <= allowed ? GAS_SIG_OK : GAS_SIG_UNSTABLE;
}
