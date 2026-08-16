import { env } from "cloudflare:workers";

export function getD1(): D1Database {
  const runtime = env as unknown as { DB?: D1Database };
  if (!runtime.DB) throw new Error("D1 binding DB is unavailable");
  return runtime.DB;
}
