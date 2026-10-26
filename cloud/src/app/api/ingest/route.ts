import { MIN_SECRET_LEN, verify } from "@/lib/hmac";
import { historyPoint, SnapshotSchema } from "@/lib/schema";
import { claimTimestamp, saveSnapshot } from "@/lib/store";

// POST /api/ingest -- the only write path, used by the host daemon.
// Order matters: everything that costs nothing (size, signature, schema)
// runs before the first Redis command, so junk can't burn the free quota.

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BODY = 32 * 1024;

function reply(status: number, error?: string): Response {
  return new Response(error ? JSON.stringify({ error }) : null, {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export async function POST(req: Request): Promise<Response> {
  const secret = process.env.INGEST_HMAC_SECRET ?? "";
  if (secret.length < MIN_SECRET_LEN) return reply(503, "ingest not configured");

  const declared = Number(req.headers.get("content-length") ?? "0");
  if (declared > MAX_BODY) return reply(413, "too large");
  const body = await req.text();
  if (body.length > MAX_BODY) return reply(413, "too large");

  const now = Math.floor(Date.now() / 1000);
  const v = verify(secret, req.headers.get("x-clawd-ts"), req.headers.get("x-clawd-sig"), body, now);
  if (!v.ok) return reply(401, v.reason);

  let json: unknown;
  try {
    json = JSON.parse(body);
  } catch {
    return reply(400, "bad json");
  }
  const parsed = SnapshotSchema.safeParse(json);
  if (!parsed.success) return reply(400, "schema");

  try {
    if (!(await claimTimestamp(v.ts))) return reply(409, "replay");
    await saveSnapshot({ received_at: now, snapshot: parsed.data }, historyPoint(parsed.data, now));
  } catch {
    return reply(503, "storage unavailable"); // detail stays in the server log only
  }
  return reply(204);
}
