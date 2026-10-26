import { ownerSession } from "@/lib/auth";
import { loadSnapshot } from "@/lib/store";

// GET /api/snapshot -- the dashboard's poll. Owner session required.

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const HEADERS = { "content-type": "application/json", "cache-control": "no-store" };

export async function GET(): Promise<Response> {
  if (!(await ownerSession())) {
    return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401, headers: HEADERS });
  }
  let data;
  try {
    data = await loadSnapshot();
  } catch {
    return new Response(JSON.stringify({ error: "storage unavailable" }), { status: 503, headers: HEADERS });
  }
  return new Response(JSON.stringify({ now: Math.floor(Date.now() / 1000), ...data }), {
    headers: HEADERS,
  });
}
