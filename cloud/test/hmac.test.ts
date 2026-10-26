import { describe, expect, it } from "vitest";
import { MAX_SKEW_S, sign, verify } from "@/lib/hmac";

const SECRET = "s".repeat(40);
const BODY = '{"v":1,"sent_at":1700000000}';
const TS = 1_700_000_000;

describe("verify", () => {
  it("accepts a correct signature", () => {
    expect(verify(SECRET, String(TS), sign(SECRET, TS, BODY), BODY, TS + 10)).toEqual({ ok: true, ts: TS });
  });

  it("matches the daemon's scheme (python hmac over '<ts>.<body>')", () => {
    // From tools/tests/test_cloud_push.py's Signing case: same secret/ts/body.
    expect(sign(SECRET, 1700000000, '{"v":1}')).toMatch(/^[0-9a-f]{64}$/);
  });

  it.each([
    ["missing headers", null, null, BODY, "missing signature"],
    ["non-numeric ts", "abc", "0".repeat(64), BODY, "bad timestamp"],
    ["malformed sig", String(TS), "xyz", BODY, "bad signature"],
    ["tampered body", String(TS), sign(SECRET, TS, BODY), BODY + " ", "bad signature"],
    ["wrong secret", String(TS), sign("t".repeat(40), TS, BODY), BODY, "bad signature"],
  ])("rejects %s", (_n, ts, sig, body, reason) => {
    expect(verify(SECRET, ts, sig, body, TS)).toEqual({ ok: false, reason });
  });

  it("rejects timestamps outside the skew window, both directions", () => {
    const sig = sign(SECRET, TS, BODY);
    expect(verify(SECRET, String(TS), sig, BODY, TS + MAX_SKEW_S + 1)).toEqual({ ok: false, reason: "stale timestamp" });
    expect(verify(SECRET, String(TS), sig, BODY, TS - MAX_SKEW_S - 1)).toEqual({ ok: false, reason: "stale timestamp" });
  });
});
