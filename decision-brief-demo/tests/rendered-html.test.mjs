import assert from "node:assert/strict";
import { access } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the GLAP customer control tower", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>GLAP Logistics Decision Platform<\/title>/i);
  assert.match(html, /Control Tower/);
  assert.match(html, /Network risk picture/);
  assert.match(html, /Needs your attention/);
  assert.match(html, /Divert 8 FCL via Melbourne/);
  assert.match(html, /Value delivered/);
  assert.match(html, /property="og:image" content="\/og\.png"/);
});

test("includes the generated social card", async () => {
  await access(new URL("../public/og.png", import.meta.url));
});
