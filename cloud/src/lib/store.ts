import { Redis } from "@upstash/redis";
import type { HistoryPoint, Snapshot } from "./schema";

// Upstash Redis (Vercel Marketplace, free tier: 500k commands/month).
// Budget at one push a minute: ~4 commands per ingest (replay check, latest,
// LPUSH, LTRIM) = ~175k/month, plus 2 per dashboard poll.

const K_LATEST = "clawd:latest";
const K_HISTORY = "clawd:history";
const K_LAST_TS = "clawd:last_ts";
export const HISTORY_LEN = 1440; // 24 h at one point a minute

let client: Redis | null = null;

function redis(): Redis {
  if (client) return client;
  // The Marketplace integration injects KV_REST_API_*; a manual Upstash setup
  // uses UPSTASH_REDIS_REST_*. Accept either.
  const url = process.env.UPSTASH_REDIS_REST_URL ?? process.env.KV_REST_API_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN ?? process.env.KV_REST_API_TOKEN;
  if (!url || !token) throw new Error("Redis is not configured");
  client = new Redis({ url, token });
  return client;
}

// Atomic "newer than the last accepted timestamp" check: a captured request
// can't be replayed, even inside the 5-minute signing window.
const REPLAY_LUA = `
local c = redis.call('GET', KEYS[1])
if c and tonumber(c) >= tonumber(ARGV[1]) then return 0 end
redis.call('SET', KEYS[1], ARGV[1])
return 1`;

export async function claimTimestamp(ts: number): Promise<boolean> {
  const r = await redis().eval(REPLAY_LUA, [K_LAST_TS], [String(ts)]);
  return r === 1;
}

export type Stored = { received_at: number; snapshot: Snapshot };

export async function saveSnapshot(stored: Stored, point: HistoryPoint): Promise<void> {
  const p = redis().pipeline();
  p.set(K_LATEST, JSON.stringify(stored));
  p.lpush(K_HISTORY, JSON.stringify(point));
  p.ltrim(K_HISTORY, 0, HISTORY_LEN - 1);
  await p.exec();
}

export async function loadSnapshot(): Promise<{ latest: Stored | null; history: HistoryPoint[] }> {
  const p = redis().pipeline();
  p.get(K_LATEST);
  p.lrange(K_HISTORY, 0, HISTORY_LEN - 1);
  const [latest, history] = (await p.exec()) as [Stored | string | null, (HistoryPoint | string)[]];
  // @upstash/redis auto-parses JSON values; tolerate raw strings too.
  const parse = <T,>(v: T | string): T => (typeof v === "string" ? (JSON.parse(v) as T) : v);
  return {
    latest: latest == null ? null : parse(latest),
    history: (history ?? []).map(parse).reverse(), // oldest first
  };
}
