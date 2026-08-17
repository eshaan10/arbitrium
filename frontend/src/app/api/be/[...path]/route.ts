import { NextRequest } from "next/server";
import { BACKEND_URL } from "@/lib/api";

/**
 * Read-only proxy to the FastAPI backend.
 *
 * Exists so the browser never needs the backend origin (no CORS policy to keep
 * in sync, no internal hostname shipped to the client). Only GET is forwarded —
 * every endpoint this app uses is a read, and the backend has no mutating route
 * that a browser should be able to reach through here.
 */

const ALLOWED = [
  /^divergences$/,
  /^events\/[^/]+\/history$/,
  /^events\/lookup$/,
  /^events\/[^/]+$/,
  /^performance$/,
  /^health$/,
  /^activity$/,
];

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const joined = path.join("/");

  if (!ALLOWED.some((re) => re.test(joined))) {
    return Response.json({ detail: "Not proxied" }, { status: 404 });
  }

  const url = `${BACKEND_URL}/${joined}${req.nextUrl.search}`;

  try {
    const upstream = await fetch(url, {
      headers: { accept: "application/json" },
      cache: "no-store",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
      },
    });
  } catch {
    // The backend being down is an expected state during Phase 3 work, and the
    // UI has a real empty state for it — so say so plainly rather than 500ing
    // with a stack the user can't act on.
    return Response.json({ detail: "Backend unreachable" }, { status: 503 });
  }
}
