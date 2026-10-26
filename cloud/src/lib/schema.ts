import { z } from "zod";

// The ingest contract. Every object is strict: a field the daemon didn't
// mean to send (or an attacker with the secret tries to add) is rejected,
// not stored. Mirrors daemon/cloud_push.py's build_snapshot(); the shared
// fixture tools/fixtures/cloud_snapshot.json pins both sides.

// Bounded but roomy: unix timestamps (~1.8e9) must fit.
const num = z.number().finite().min(-1e10).max(1e10);
const str = (max: number) => z.string().max(max);
const level = z.enum(["good", "fair", "poor", "bad"]);
const gas = z.strictObject({ ppm: num.min(0), level });

// Links are rendered as <a href>, so only GitHub https URLs get through --
// never javascript:, data:, or anything else.
const githubUrl = str(300).refine((s) => s === "" || s.startsWith("https://github.com/"), {
  message: "only https://github.com/ links",
});

export const SnapshotSchema = z.strictObject({
  v: z.literal(1),
  sent_at: num, // daemon clock, unix seconds

  air: z
    .strictObject({
      present: z.boolean(),
      warming: z.boolean(),
      calibrated: z.boolean(),
      mv: num,
      ratio: num.min(0),
      level,
      saturated: z.boolean(),
      hint: z.enum(["", "spike", "slow"]),
      gases: z.strictObject({
        co2: gas, nh3: gas, alcohol: gas, toluene: gas, acetone: gas, co: gas,
      }),
    })
    .optional(),
  indoor: z
    .strictObject({
      present: z.boolean(),
      temp_c: num.nullable(),
      pressure_hpa: num.nullable(),
      humidity_pct: num.nullable(),
    })
    .optional(),
  claude: z
    .strictObject({
      session_pct: num, session_reset_mins: num,
      weekly_pct: num, weekly_reset_mins: num,
      status: str(32), model: str(32), ctx_pct: num, valid: z.boolean(),
    })
    .optional(),
  activity: z.strictObject({ state: str(16), agents: num }).optional(),
  copilot: z
    .strictObject({
      premium_pct: num, premium_total: num, premium_reset_str: str(16),
      plan: str(24), valid: z.boolean(),
    })
    .optional(),
  codex: z
    .strictObject({
      p1: num, p2: num, w1: num, w2: num, r1: num, r2: num, ts: num,
      st: str(16), plan: str(24), valid: z.boolean(),
    })
    .optional(),
  sysinfo: z
    .strictObject({ cpu_pct: num, ram_pct: num, disk_pct: num, cpu_temp: num, valid: z.boolean() })
    .optional(),
  today: z
    .strictObject({
      active_min: num, tok_k: num, usd: num, commits: num, cp_used: num, valid: z.boolean(),
    })
    .optional(),
  device: z
    .strictObject({
      uptime_s: num, heap_free: num, heap_min_free: num,
      wifi_ok: z.boolean(), daemon_state: str(32),
    })
    .optional(),

  // Opt-in sections (daemon config cloud_sections) -- off by default.
  weather: z
    .strictObject({
      temp_c: num, hi_c: num, lo_c: num, wcode: num, loc: str(24),
      aurora_pct: num, kp_x10: num, cloud_pct: num, night: z.boolean(),
    })
    .optional(),
  ci: z
    .strictObject({
      state: str(16), review: num, total: num,
      items: z
        .array(
          z.strictObject({
            state: str(16), repo: str(80), title: str(120), branch: str(80),
            workflow: str(80), job: str(80), step: str(80), pr: num, url: githubUrl,
          }),
        )
        .max(4),
    })
    .optional(),
  vscode: z
    .strictObject({ mem_mb: num, cpu_pct: num, ext_count: num, error_count: num })
    .optional(),
});

export type Snapshot = z.infer<typeof SnapshotSchema>;

// One point of 24 h history, derived server-side from the snapshot at ingest
// -- never taken from the request as-is.
export type HistoryPoint = {
  t: number; // received_at, unix seconds
  ar: number | null; // air Rs/R0
  cs: number | null; // Claude session %
  cw: number | null; // Claude weekly %
  cpu: number | null;
  it: number | null; // indoor temp
};

export function historyPoint(s: Snapshot, t: number): HistoryPoint {
  const ok = <T,>(cond: boolean | undefined, v: T) => (cond ? v : null);
  return {
    t,
    ar: ok(s.air?.present && !s.air.warming, s.air?.ratio ?? null),
    cs: ok(s.claude?.valid, s.claude?.session_pct ?? null),
    cw: ok(s.claude?.valid, s.claude?.weekly_pct ?? null),
    cpu: ok(s.sysinfo?.valid, s.sysinfo?.cpu_pct ?? null),
    it: s.indoor?.present ? s.indoor.temp_c : null,
  };
}
