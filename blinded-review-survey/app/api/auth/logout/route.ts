import { clearSessionCookie, sameOrigin } from "../../../account-auth";

export async function POST(request: Request) {
  if (!sameOrigin(request)) return Response.json({ error: "Request origin rejected" }, { status: 403 });
  return Response.json({ ok: true }, { headers: { "set-cookie": clearSessionCookie(request), "cache-control": "no-store" } });
}
