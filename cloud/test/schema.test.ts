import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { historyPoint, SnapshotSchema } from "@/lib/schema";

// Same file tools/tests/test_cloud_push.py pins the daemon's output to.
const fixture = JSON.parse(
  readFileSync(new URL("../../tools/fixtures/cloud_snapshot.json", import.meta.url), "utf8"),
);
const clone = () => JSON.parse(JSON.stringify(fixture));

describe("SnapshotSchema", () => {
  it("accepts what the daemon actually sends (all sections)", () => {
    const r = SnapshotSchema.safeParse(fixture);
    expect(r.success, JSON.stringify(r.error?.issues)).toBe(true);
  });

  it("accepts a minimal snapshot", () => {
    expect(SnapshotSchema.safeParse({ v: 1, sent_at: 1 }).success).toBe(true);
  });

  it("rejects unknown fields at any depth", () => {
    const top = clone(); top.wifi_ip = "192.0.2.1";
    const deep = clone(); deep.claude.token = "x";
    expect(SnapshotSchema.safeParse(top).success).toBe(false);
    expect(SnapshotSchema.safeParse(deep).success).toBe(false);
  });

  it("rejects non-GitHub links", () => {
    for (const url of ["javascript:alert(1)", "https://evil.example/", "http://github.com/x"]) {
      const s = clone(); s.ci.items[0].url = url;
      expect(SnapshotSchema.safeParse(s).success, url).toBe(false);
    }
  });

  it("bounds strings and arrays", () => {
    const longTitle = clone(); longTitle.ci.items[0].title = "x".repeat(121);
    const many = clone(); many.ci.items = Array(5).fill(fixture.ci.items[0]);
    const badLevel = clone(); badLevel.air.level = "<b>";
    for (const s of [longTitle, many, badLevel]) expect(SnapshotSchema.safeParse(s).success).toBe(false);
  });

  it("rejects the wrong version", () => {
    const s = clone(); s.v = 2;
    expect(SnapshotSchema.safeParse(s).success).toBe(false);
  });
});

describe("historyPoint", () => {
  it("derives from the snapshot, nulling what isn't valid", () => {
    const s = SnapshotSchema.parse(fixture);
    expect(historyPoint(s, 42)).toEqual({ t: 42, ar: 3.824, cs: 21, cw: 88, cpu: 33, it: 22.4 });
    const warming = SnapshotSchema.parse({ ...clone(), air: { ...fixture.air, warming: true } });
    expect(historyPoint(warming, 1).ar).toBeNull();
  });
});
