import { createHmac, timingSafeEqual } from "node:crypto";

// Request signing for POST /api/ingest. The daemon (daemon/cloud_push.py)
// sends X-Clawd-Ts (unix seconds) and X-Clawd-Sig = hex HMAC-SHA256 over
// "<ts>.<raw body>" with the shared INGEST_HMAC_SECRET. Verified before the
// body is parsed or Redis is touched, so an unsigned flood can't spend the
// free tier's command quota.

export const MAX_SKEW_S = 300;
export const MIN_SECRET_LEN = 32;

export function sign(secret: string, ts: number, body: string): string {
  return createHmac("sha256", Buffer.from(secret, "utf8")).update(`${ts}.${body}`).digest("hex");
}

export type VerifyResult = { ok: true; ts: number } | { ok: false; reason: string };

export function verify(
  secret: string,
  tsHeader: string | null,
  sigHeader: string | null,
  body: string,
  nowS: number,
): VerifyResult {
  if (!tsHeader || !sigHeader) return { ok: false, reason: "missing signature" };
  if (!/^\d{1,12}$/.test(tsHeader)) return { ok: false, reason: "bad timestamp" };
  if (!/^[0-9a-f]{64}$/.test(sigHeader)) return { ok: false, reason: "bad signature" };
  const ts = Number(tsHeader);
  if (Math.abs(nowS - ts) > MAX_SKEW_S) return { ok: false, reason: "stale timestamp" };
  const want = Buffer.from(sign(secret, ts, body), "hex");
  const got = Buffer.from(sigHeader, "hex");
  if (got.length !== want.length || !timingSafeEqual(got, want)) {
    return { ok: false, reason: "bad signature" };
  }
  return { ok: true, ts };
}
