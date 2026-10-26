#include "gas_sensor.h"
#include "env_sensor.h"
#include <Arduino.h>
#include <Preferences.h>
#include <math.h>

namespace {

#define GAS_VC_MV         5000.0f   // module supply (USB 5V)
#define GAS_SAMPLE_MS     1000
#define GAS_OVERSAMPLE    32
#define GAS_EMA_ALPHA     0.2f
#define GAS_WARMUP_S      180       // heater settle time after power-up
#define GAS_ABSENT_MV     50        // below this at S, nothing is connected
#define GAS_SAT_PIN_MV    3050      // ADC ceiling at 11 dB attenuation
#define GAS_SAT_MV        4900      // S output pinned at the supply rail
#define GAS_DS_CLEAN      3.6f      // datasheet Rs/R0 in clean air (its R0 != ours)
#define GAS_SLOW_ALPHA    (1.0f / 600)   // ~10 min trend, for the source hint
#define GAS_SPIKE_DROP    0.85f     // ratio fell >15% below the 10-min trend
#define GAS_PERSIST_MS    (10UL * 60 * 1000)   // auto-baseline NVS write cadence

bool     sampled     = false;
uint32_t last_ms     = 0;
float    mv_ema      = 0;       // sensor output (divider undone), smoothed
int      pin_mv      = 0;       // last raw pin reading, for saturation check
float    r_now       = 0;       // Rs/RL, temp/humidity-normalised
float    r0          = 0;       // baseline Rs/RL; 0 = not yet established
float    r_slow      = 0;       // ~10-min EMA of r_now, for the hint
bool     calibrated  = false;
bool     r0_dirty    = false;
uint32_t r0_saved_ms = 0;

// Temp/humidity dependence of the MQ-135, normalised to 20 C / 33 %RH — the
// fit popularised by the GeorgK MQ135 library from the datasheet's Fig. 4.
float env_factor(void) {
    if (!env_sensor_is_present()) return 1.0f;
    float t = env_sensor_temp_c();
    float h = env_sensor_has_humidity() ? env_sensor_humidity_pct() : 33.0f;
    float f = 0.00035f * t * t - 0.02718f * t + 1.39538f - (h - 33.0f) * 0.0018f;
    return f > 0.2f ? f : 1.0f;   // guard against a garbage reading
}

void save_r0(void) {
    Preferences p;
    if (!p.begin("gas", false)) return;
    p.putFloat("r0", r0);
    p.putUChar("cal", calibrated ? 1 : 0);
    p.end();
    r0_dirty    = false;
    r0_saved_ms = millis();
}

bool is_present(void)  { return sampled && mv_ema >= GAS_ABSENT_MV; }
bool is_warming(void)  { return millis() < GAS_WARMUP_S * 1000UL; }

float ratio_now(void) { return (r0 > 0 && r_now > 0) ? r_now / r0 : 1.0f; }

// Our R0 is the clean-air resistance (ratio 1.0); the datasheet's is defined
// so clean air reads 3.6. Each curve is evaluated as the *excess* over what it
// gives for clean air, so clean air reads 0 (plus CO2's ambient base) rather
// than a few ppm of every gas at once.
float gas_ppm(const GasDef& g, float ratio) {
    float excess = g.a * (powf(GAS_DS_CLEAN * ratio, g.b) - powf(GAS_DS_CLEAN, g.b));
    return g.base + (excess > 0 ? excess : 0);
}

AirLevel gas_level(const GasDef& g, float ppm) {
    if (ppm >= g.alarm)          return AIR_BAD;
    if (ppm >= g.caution)        return AIR_POOR;
    if (ppm >= g.caution * 0.5f) return AIR_FAIR;
    return AIR_GOOD;
}

}  // namespace

// Thresholds are total ppm. Where a recognised exposure limit falls inside the
// curve's range it's used; the sources are noted per row. Note that by the
// datasheet's own CO2 curve the MQ-135 is nearly blind to CO2 -- halving Rs
// adds only ~20 ppm -- so that row rarely leaves "Good" even in a stuffy room.
const GasDef GAS_DEFS[AIR_GAS_COUNT] = {
    // key        name       a         b       base lo  hi    caution alarm
    { "co2",     "CO2",     110.47f,  -2.862f, 400, 10, 1000, 1000, 2000 },  // ventilation guidance
    { "nh3",     "NH3",     102.2f,   -2.473f,   0, 10, 1000,   25,   35 },  // NIOSH REL TWA / STEL
    { "alcohol", "Alcohol",  77.255f, -3.18f,    0, 10, 1000,  500, 1000 },  // ethanol; ACGIH STEL 1000
    { "toluene", "Toluene",  44.947f, -3.445f,   0, 10, 1000,   20,  100 },  // ACGIH TLV / NIOSH REL
    { "acetone", "Acetone",  34.668f, -3.369f,   0, 10, 1000,  250,  500 },  // ACGIH TLV / STEL
    { "co",      "CO",      605.18f,  -3.937f,   0, 10, 1000,    9,   35 },  // EPA 8 h / 1 h -- NOT a CO alarm
};

void gas_sensor_init(void) {
    // Core 3.x only accepts an attenuation for a pin already set up as an ADC
    // channel, which the first analogRead() does.
    analogRead(GAS_PIN);
    analogSetPinAttenuation(GAS_PIN, ADC_11db);   // ~0-3.1 V range

    // Read-write open: first-ever access to a namespace crashes read-only
    // (CLAUDE.md gotcha #11).
    Preferences p;
    if (p.begin("gas", false)) {
        r0         = p.getFloat("r0", 0);
        calibrated = p.getUChar("cal", 0) != 0;
        p.end();
    }
    if (!(r0 > 0)) { r0 = 0; calibrated = false; }
    Serial.printf("gas sensor: GPIO%d, R0=%.3f (%s)\n", GAS_PIN, (double)r0,
                  calibrated ? "calibrated" : r0 > 0 ? "auto" : "none yet");
}

void gas_sensor_tick(void) {
    uint32_t now = millis();
    if (sampled && now - last_ms < GAS_SAMPLE_MS) return;
    last_ms = now;

    uint32_t sum = 0;
    for (int i = 0; i < GAS_OVERSAMPLE; i++) sum += analogReadMilliVolts(GAS_PIN);
    pin_mv = (int)(sum / GAS_OVERSAMPLE);
    float mv = pin_mv * GAS_DIVIDER;

    mv_ema  = sampled ? mv_ema + GAS_EMA_ALPHA * (mv - mv_ema) : mv;
    sampled = true;
    if (!is_present()) return;

    // Rs/RL straight from the divider the module forms with its load
    // resistor. RL itself cancels out of Rs/R0, so its value never matters.
    float v = mv_ema < GAS_VC_MV - 1 ? mv_ema : GAS_VC_MV - 1;
    r_now = (GAS_VC_MV - v) / v / env_factor();
    r_slow = (r_slow > 0) ? r_slow + GAS_SLOW_ALPHA * (r_now - r_slow) : r_now;

    // Auto baseline: the cleanest (highest-resistance) air seen since the
    // heater settled. Pinned once `gascal` has been run.
    if (!calibrated && !is_warming() && r_now > r0) {
        r0 = r_now;
        r0_dirty = true;
    }
    if (r0_dirty && (r0_saved_ms == 0 || now - r0_saved_ms >= GAS_PERSIST_MS)) save_r0();
}

bool gas_sensor_get(AirData* out) {
    if (!sampled) return false;
    out->present     = is_present();
    out->warming     = is_warming();
    out->warm_left_s = out->warming ? (int)(GAS_WARMUP_S - millis() / 1000UL) : 0;
    out->calibrated  = calibrated;
    out->mv          = (int)lroundf(mv_ema);
    out->ratio       = ratio_now();
    out->saturated   = pin_mv >= GAS_SAT_PIN_MV || mv_ema >= GAS_SAT_MV;

    // Headline: the ratio itself, no gas assumed.
    float r = out->ratio;
    if (out->saturated || r < 0.55f) out->level = AIR_BAD;
    else if (r < 0.70f)              out->level = AIR_POOR;
    else if (r < 0.85f)              out->level = AIR_FAIR;
    else                             out->level = AIR_GOOD;

    // Fast drop below the 10-minute trend = something just got released
    // (sanitizer, cooking, spray). Down for a while with no spike = air has
    // gone stale gradually (people, poor ventilation). Educated guesses.
    out->hint = AIR_HINT_NONE;
    if (!out->warming && out->present && r_slow > 0) {
        if (r_now < r_slow * GAS_SPIKE_DROP) out->hint = AIR_HINT_SPIKE;
        else if (r < 0.85f)                  out->hint = AIR_HINT_SLOW;
    }

    for (int i = 0; i < AIR_GAS_COUNT; i++) {
        out->gas_ppm[i]   = gas_ppm(GAS_DEFS[i], r);
        out->gas_level[i] = out->saturated ? AIR_BAD : gas_level(GAS_DEFS[i], out->gas_ppm[i]);
    }
    return true;
}

void gas_sensor_print(void) {
    AirData a;
    if (!gas_sensor_get(&a)) { Serial.println("gas: no sample yet"); return; }
    Serial.printf("gas: pin=%dmV S=%dmV Rs/RL=%.3f R0=%.3f (%s) ratio=%.3f level=%d hint=%d%s%s%s\n",
                  pin_mv, a.mv, (double)r_now, (double)r0,
                  calibrated ? "cal" : "auto", (double)a.ratio, (int)a.level, (int)a.hint,
                  a.present ? "" : " ABSENT", a.warming ? " warming" : "",
                  a.saturated ? " SATURATED" : "");
    Serial.print("     ");
    for (int i = 0; i < AIR_GAS_COUNT; i++)
        Serial.printf(" %s=%.1f", GAS_DEFS[i].key, (double)a.gas_ppm[i]);
    Serial.println(" (ppm equivalents)");
}

GasCalResult gas_sensor_calibrate(bool allow_warming) {
    if (!is_present() || !(r_now > 0)) return GAS_CAL_NO_SENSOR;
    if (!allow_warming && is_warming()) return GAS_CAL_WARMING;
    r0 = r_now;
    calibrated = true;
    save_r0();
    return GAS_CAL_OK;
}

void gas_sensor_auto(void) {
    calibrated = false;
    r0 = is_present() ? r_now : 0;
    save_r0();
}
