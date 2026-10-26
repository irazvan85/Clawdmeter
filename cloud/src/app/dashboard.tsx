"use client";

import { useEffect, useState } from "react";
import type { HistoryPoint, Snapshot } from "@/lib/schema";

// Read-only view. Polls /api/snapshot; there is deliberately no control path
// back to the device (no screen nav, settings, or calibration from here).

type Payload = {
  now: number;
  latest: { received_at: number; snapshot: Snapshot } | null;
  history: HistoryPoint[];
};

const POLL_MS = 30_000;
const STALE_S = 180;
const OFFLINE_S = 600;

export default function Dashboard() {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const r = await fetch("/api/snapshot", { cache: "no-store" });
        if (r.status === 401) {
          window.location.href = "/";
          return;
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const p = (await r.json()) as Payload;
        if (alive) {
          setData(p);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "unreachable");
      }
    }
    load();
    const poll = setInterval(load, POLL_MS);
    const tick = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => {
      alive = false;
      clearInterval(poll);
      clearInterval(tick);
    };
  }, []);

  const s = data?.latest?.snapshot;
  const age = data?.latest ? now - data.latest.received_at : null;
  const fresh = age == null ? "offline" : age > OFFLINE_S ? "offline" : age > STALE_S ? "stale" : "ok";
  const h = data?.history ?? [];

  return (
    <main>
      <header>
        <h1>Clawdmeter</h1>
        <span className={`pill ${fresh}`}>
          <span className="dot" />
          {age == null ? "no data yet" : `updated ${fmtAge(age)} ago`}
          {fresh === "stale" && " · stale"}
          {fresh === "offline" && age != null && " · offline"}
        </span>
        <a className="signout" href="/api/auth/signout">
          Sign out
        </a>
      </header>
      {error && <p className="warn">Couldn&apos;t refresh: {error}</p>}
      {!s ? (
        <p className="dim">Waiting for the first push from the daemon.</p>
      ) : (
        <div className="grid">
          {s.air && <AirCard air={s.air} hist={h} />}
          {s.indoor && <IndoorCard indoor={s.indoor} hist={h} />}
          {s.claude && <ClaudeCard s={s} hist={h} />}
          {(s.copilot || s.codex) && <QuotaCard s={s} />}
          {s.today && <TodayCard today={s.today} />}
          {s.sysinfo && <HostCard s={s} hist={h} />}
          {s.weather && <WeatherCard w={s.weather} />}
          {s.ci && <CiCard ci={s.ci} />}
        </div>
      )}
    </main>
  );
}

// ---------------------------------------------------------------- cards

const LEVEL_CLASS = { good: "good", fair: "fair", poor: "bad", bad: "bad" } as const;
const GAS_NAMES = { co2: "CO2", nh3: "NH3", alcohol: "Alcohol", toluene: "Toluene", acetone: "Acetone", co: "CO" };

function AirCard({ air, hist }: { air: NonNullable<Snapshot["air"]>; hist: HistoryPoint[] }) {
  const hint = air.hint === "spike" ? "Sudden spike: VOC/alcohol?" : air.hint === "slow" ? "Gradual: stale air?" : null;
  return (
    <section className="card">
      <h2>Air</h2>
      {!air.present ? (
        <p className="dim">No sensor</p>
      ) : air.warming ? (
        <p className="big dim">Warming up</p>
      ) : (
        <>
          <p className={`big ${LEVEL_CLASS[air.level]}`}>{cap(air.level)}</p>
          <Row k="Rs/R0" v={air.ratio.toFixed(2)} />
          <Row k="Baseline" v={air.calibrated ? "calibrated" : "auto"} />
          {hint && <p className="fair small">{hint}</p>}
          <Spark pts={hist} pick={(p) => p.ar} label="24 h Rs/R0" digits={2} />
          <h3>Gas equivalents (ppm, one sensor)</h3>
          {(Object.keys(GAS_NAMES) as (keyof typeof GAS_NAMES)[]).map((k) => (
            <Row key={k} k={GAS_NAMES[k]} v={Math.round(air.gases[k].ppm)} cls={LEVEL_CLASS[air.gases[k].level]} />
          ))}
        </>
      )}
    </section>
  );
}

function IndoorCard({ indoor, hist }: { indoor: NonNullable<Snapshot["indoor"]>; hist: HistoryPoint[] }) {
  return (
    <section className="card">
      <h2>Indoor</h2>
      {!indoor.present ? (
        <p className="dim">No sensor</p>
      ) : (
        <>
          <p className="big">{indoor.temp_c == null ? "--" : `${indoor.temp_c.toFixed(1)} °C`}</p>
          {indoor.humidity_pct != null && <Row k="Humidity" v={`${Math.round(indoor.humidity_pct)} %`} />}
          {indoor.pressure_hpa != null && <Row k="Pressure" v={`${Math.round(indoor.pressure_hpa)} hPa`} />}
          <Spark pts={hist} pick={(p) => p.it} label="24 h °C" digits={1} />
        </>
      )}
    </section>
  );
}

function ClaudeCard({ s, hist }: { s: Snapshot; hist: HistoryPoint[] }) {
  const c = s.claude!;
  return (
    <section className="card">
      <h2>Claude</h2>
      {!c.valid ? (
        <p className="dim">No data</p>
      ) : (
        <>
          <Bar label="Session (5 h)" pct={c.session_pct} sub={`resets in ${fmtMins(c.session_reset_mins)}`} />
          <Bar label="Weekly" pct={c.weekly_pct} sub={`resets in ${fmtMins(c.weekly_reset_mins)}`} />
          <Row k="Model" v={c.model || "--"} />
          {s.activity && <Row k="Activity" v={s.activity.state.replace("_", " ")} />}
          <Spark pts={hist} pick={(p) => p.cs} label="24 h session %" digits={0} />
        </>
      )}
    </section>
  );
}

function QuotaCard({ s }: { s: Snapshot }) {
  return (
    <section className="card">
      <h2>Quotas</h2>
      {s.copilot?.valid && (
        <Bar label={`Copilot ${s.copilot.plan}`} pct={s.copilot.premium_pct} sub={`resets ${s.copilot.premium_reset_str}`} />
      )}
      {s.codex?.valid && (
        <>
          <Bar label={`Codex ${fmtWindow(s.codex.w1)}`} pct={s.codex.p1} />
          <Bar label={`Codex ${fmtWindow(s.codex.w2)}`} pct={s.codex.p2} />
        </>
      )}
      {!s.copilot?.valid && !s.codex?.valid && <p className="dim">No data</p>}
    </section>
  );
}

function TodayCard({ today }: { today: NonNullable<Snapshot["today"]> }) {
  return (
    <section className="card">
      <h2>Today</h2>
      {!today.valid ? (
        <p className="dim">No data</p>
      ) : (
        <>
          <Row k="Active" v={`${today.active_min} min`} />
          <Row k="Tokens" v={`${today.tok_k}k`} />
          <Row k="Cost" v={today.usd >= 0 ? `$${today.usd}` : "--"} />
          <Row k="Commits" v={today.commits} />
        </>
      )}
    </section>
  );
}

function HostCard({ s, hist }: { s: Snapshot; hist: HistoryPoint[] }) {
  const si = s.sysinfo!;
  const d = s.device;
  return (
    <section className="card">
      <h2>Host &amp; device</h2>
      {si.valid && (
        <>
          <Bar label="CPU" pct={si.cpu_pct} />
          <Bar label="RAM" pct={si.ram_pct} />
          <Bar label="Disk" pct={si.disk_pct} />
          <Spark pts={hist} pick={(p) => p.cpu} label="24 h CPU %" digits={0} />
        </>
      )}
      {d && (
        <>
          <Row k="Device WiFi" v={d.wifi_ok ? "connected" : "down"} cls={d.wifi_ok ? "good" : "bad"} />
          <Row k="Device uptime" v={fmtMins(Math.floor(d.uptime_s / 60))} />
          <Row k="Free heap (min)" v={`${Math.round(d.heap_free / 1024)} KB (${Math.round(d.heap_min_free / 1024)})`} />
        </>
      )}
    </section>
  );
}

function WeatherCard({ w }: { w: NonNullable<Snapshot["weather"]> }) {
  return (
    <section className="card">
      <h2>Weather · {w.loc}</h2>
      <p className="big">{w.temp_c} °C</p>
      <Row k="High / low" v={`${w.hi_c} / ${w.lo_c} °C`} />
      <Row k="Aurora" v={w.aurora_pct >= 0 ? `${w.aurora_pct} %` : "--"} />
      <Row k="Kp" v={w.kp_x10 >= 0 ? (w.kp_x10 / 10).toFixed(1) : "--"} />
    </section>
  );
}

function CiCard({ ci }: { ci: NonNullable<Snapshot["ci"]> }) {
  return (
    <section className="card">
      <h2>Checks</h2>
      <Row k="Reviews waiting" v={ci.review} />
      {ci.items.map((it, i) => (
        <div key={i} className="ci-item">
          <span className={it.state === "fail" ? "bad" : it.state === "pass" ? "good" : "dim"}>{it.state}</span>{" "}
          {it.url ? (
            <a href={it.url} rel="noreferrer noopener" target="_blank">
              {it.repo}
              {it.pr ? ` #${it.pr}` : ""}
            </a>
          ) : (
            it.repo
          )}
          {it.title && <div className="dim small">{it.title}</div>}
        </div>
      ))}
    </section>
  );
}

// ---------------------------------------------------------------- bits

function Row({ k, v, cls }: { k: string; v: string | number; cls?: string }) {
  return (
    <div className="row">
      <span className="dim">{k}</span>
      <span className={cls}>{v}</span>
    </div>
  );
}

function Bar({ label, pct, sub }: { label: string; pct: number; sub?: string }) {
  const p = Math.max(0, Math.min(100, pct));
  const cls = p >= 90 ? "bad" : p >= 70 ? "fair" : "good";
  return (
    <div className="bar-block">
      <div className="row">
        <span className="dim">{label}</span>
        <span>{pct >= 0 ? `${Math.round(pct)} %` : "--"}</span>
      </div>
      <div className="bar">
        <div className={`fill ${cls}`} style={{ width: `${p}%` }} />
      </div>
      {sub && <div className="dim small">{sub}</div>}
    </div>
  );
}

// 24 h sparkline; gaps (device/daemon offline) break the line rather than
// bridging it.
function Spark({ pts, pick, label, digits }: {
  pts: HistoryPoint[]; pick: (p: HistoryPoint) => number | null; label: string; digits: number;
}) {
  const W = 260, H = 44;
  const vals = pts.map((p) => ({ t: p.t, v: pick(p) })).filter((p): p is { t: number; v: number } => p.v != null);
  if (vals.length < 2) return <p className="dim small">{label}: collecting</p>;
  const t1 = pts[pts.length - 1].t, t0 = t1 - 24 * 3600;
  let lo = Math.min(...vals.map((p) => p.v)), hi = Math.max(...vals.map((p) => p.v));
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const x = (t: number) => ((t - t0) / (t1 - t0)) * W;
  const y = (v: number) => H - 2 - ((v - lo) / (hi - lo)) * (H - 4);
  const segs: string[] = [];
  let cur: string[] = [];
  let prevT = -Infinity;
  for (const p of vals) {
    if (p.t < t0) continue;
    if (p.t - prevT > 300 && cur.length) { segs.push(cur.join(" ")); cur = []; }
    cur.push(`${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`);
    prevT = p.t;
  }
  if (cur.length) segs.push(cur.join(" "));
  return (
    <figure className="spark">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label}>
        {segs.map((s, i) => <polyline key={i} points={s} />)}
      </svg>
      <figcaption className="dim small">
        {label} · {lo.toFixed(digits)}–{hi.toFixed(digits)}
      </figcaption>
    </figure>
  );
}

function cap(s: string) { return s.charAt(0).toUpperCase() + s.slice(1); }
function fmtAge(s: number) {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}
function fmtMins(m: number) {
  if (m < 0) return "--";
  if (m < 60) return `${m}m`;
  if (m < 1440) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${Math.floor(m / 1440)}d ${Math.floor((m % 1440) / 60)}h`;
}
function fmtWindow(m: number) {
  if (m >= 1440 && m % 1440 === 0) return `${m / 1440}d`;
  if (m >= 60 && m % 60 === 0) return `${m / 60}h`;
  return `${m}m`;
}
