#pragma once
#include <Arduino.h>

struct UsageData {
    float session_pct;       // 5-hour window utilization (0-100)
    int session_reset_mins;  // minutes until session resets
    float weekly_pct;        // 7-day window utilization (0-100)
    int weekly_reset_mins;   // minutes until weekly resets
    char status[16];         // "allowed" or "limited"
    bool ok;                 // data parse succeeded
    bool valid;              // false until first successful parse
};

struct CopilotData {
    int premium_pct;          // 0-100, % of monthly premium requests USED, -1 if unavailable
    int premium_remaining;    // requests remaining this month, -1 if unavailable
    int premium_total;        // monthly entitlement, -1 if unavailable
    int premium_reset_mins;   // minutes until monthly quota reset, -1 if unknown
    char premium_reset_str[24]; // formatted reset date from daemon, e.g. "Jun 1"
    char plan[20];            // e.g. "Pro", "Business", "Enterprise", "unknown"
    bool enabled;             // Copilot seat is active
    bool valid;               // false until first successful parse
};
