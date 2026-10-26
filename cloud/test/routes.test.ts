import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { sign } from "@/lib/hmac";

const store = vi.hoisted(() => ({
  claimTimestamp: vi.fn(async () => true),
  saveSnapshot: vi.fn(async () => {}),
  loadSnapshot: vi.fn(async () => ({ latest: null, history: [] })),
}));
const auth = vi.hoisted(() => ({ ownerSession: vi.fn(async () => false) }));
vi.mock("@/lib/store", () => store);
vi.mock("@/lib/auth", () => auth);

const { POST } = await import("@/app/api/ingest/route");
const { GET } = await import("@/app/api/snapshot/route");

const SECRET = "k".repeat(48);
const BODY = readFileSync(new URL("../../tools/fixtures/cloud_snapshot.json", import.meta.url), "utf8");

function req(body: string, headers: Record<string, string> = {}) {
  return new Request("https://x.vercel.app/api/ingest", { method: "POST", body, headers });
}
function signed(body: string, ts = Math.floor(Date.now() / 1000)) {
  return req(body, { "x-clawd-ts": String(ts), "x-clawd-sig": sign(SECRET, ts, body) });
}

describe("POST /api/ingest", () => {
  beforeEach(() => {
    vi.stubEnv("INGEST_HMAC_SECRET", SECRET);
    Object.values(store).forEach((f) => f.mockClear());
    store.claimTimestamp.mockResolvedValue(true);
  });

  it("stores a valid signed snapshot", async () => {
    const r = await POST(signed(BODY));
    expect(r.status).toBe(204);
    expect(store.saveSnapshot).toHaveBeenCalledOnce();
    const [stored, point] = store.saveSnapshot.mock.calls[0] as unknown as [
      { snapshot: { v: number } }, { ar: number },
    ];
    expect(stored.snapshot.v).toBe(1);
    expect(point.ar).toBe(3.824);
  });

  it("refuses to run without a strong secret configured", async () => {
    vi.stubEnv("INGEST_HMAC_SECRET", "short");
    expect((await POST(signed(BODY))).status).toBe(503);
  });

  it("rejects unsigned, stale and tampered requests before touching Redis", async () => {
    const old = Math.floor(Date.now() / 1000) - 3600;
    const tampered = signed(BODY);
    const cases = [
      req(BODY),
      signed(BODY, old),
      req(BODY + " ", Object.fromEntries(tampered.headers.entries())),
    ];
    for (const c of cases) expect((await POST(c)).status).toBe(401);
    expect(store.claimTimestamp).not.toHaveBeenCalled();
    expect(store.saveSnapshot).not.toHaveBeenCalled();
  });

  it("rejects bad JSON and schema violations before touching Redis", async () => {
    expect((await POST(signed("{not json"))).status).toBe(400);
    const extra = JSON.stringify({ ...JSON.parse(BODY), wifi_ip: "192.0.2.1" });
    expect((await POST(signed(extra))).status).toBe(400);
    expect(store.claimTimestamp).not.toHaveBeenCalled();
  });

  it("rejects oversized bodies", async () => {
    const big = JSON.stringify({ v: 1, sent_at: 1, pad: "x".repeat(40_000) });
    expect((await POST(signed(big))).status).toBe(413);
  });

  it("rejects replays", async () => {
    store.claimTimestamp.mockResolvedValue(false);
    expect((await POST(signed(BODY))).status).toBe(409);
    expect(store.saveSnapshot).not.toHaveBeenCalled();
  });
});

describe("GET /api/snapshot", () => {
  it("is 401 without the owner's session and never reads Redis", async () => {
    auth.ownerSession.mockResolvedValue(false);
    store.loadSnapshot.mockClear();
    const r = await GET();
    expect(r.status).toBe(401);
    expect(store.loadSnapshot).not.toHaveBeenCalled();
  });

  it("returns data, uncached, for the owner", async () => {
    auth.ownerSession.mockResolvedValue(true);
    const r = await GET();
    expect(r.status).toBe(200);
    expect(r.headers.get("cache-control")).toBe("no-store");
  });
});
