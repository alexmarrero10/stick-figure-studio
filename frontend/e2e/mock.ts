// A fake studio backend for the browser tests. Every /api request is answered here from
// fixtures.json (recorded from a real project by record-fixtures.mjs), so tests never touch
// the real server, data/app.db, config.yaml or .env, and never call Claude or ElevenLabs.

import { test as base, expect, Page } from "@playwright/test";
import { readFileSync } from "node:fs";

export const fixtures: Record<string, any> = JSON.parse(readFileSync(new URL("./fixtures.json", import.meta.url), "utf-8"));
export const PID = fixtures["/api/projects"].find((p: any) => fixtures[`/api/projects/${p.id}`])?.id ?? 1;

// A 1x1 grey PNG for every picture, audio or video file the pages load.
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mOsrwcAAYEBDhGKtQgAAAAASUVORK5CYII=", "base64");

export interface Call {
  method: string;
  path: string; // pathname + search
  body: any;
}

type Handler = (call: Call) => unknown;

export class FakeApi {
  calls: Call[] = [];
  unknown: string[] = [];
  private handlers: { method: string; path: string | RegExp; reply: Handler }[] = [];

  /** Answer `method path` with `reply` (checked before the recorded fixtures). */
  on(method: string, path: string | RegExp, reply: Handler | unknown) {
    this.handlers.unshift({ method, path, reply: typeof reply === "function" ? (reply as Handler) : () => reply });
  }

  /** Requests the page sent that match, e.g. sent("PUT", "/api/settings/config"). */
  sent(method: string, path: string | RegExp) {
    return this.calls.filter((c) => c.method === method && (typeof path === "string" ? c.path === path : path.test(c.path)));
  }

  async install(page: Page) {
    await page.route("**/api/**", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname + url.search;
      let body: any = null;
      try {
        body = req.postDataJSON();
      } catch {
        body = req.postData();
      }
      const call = { method: req.method(), path, body };
      this.calls.push(call);

      if (url.pathname.endsWith("/file")) {
        return route.fulfill({ status: 200, contentType: "image/png", body: PNG });
      }
      const h = this.handlers.find((h) => h.method === call.method && (typeof h.path === "string" ? h.path === path : h.path.test(path)));
      if (h) return route.fulfill({ json: h.reply(call) ?? null });
      if (call.method === "GET" && path in fixtures) return route.fulfill({ json: fixtures[path] });
      if (call.method === "GET" && url.pathname === "/api/jobs") return route.fulfill({ json: [] }); // no running jobs
      this.unknown.push(`${call.method} ${path}`);
      return route.fulfill({ status: 500, json: { detail: `No test answer for ${call.method} ${path}` } });
    });
  }
}

/** `api` is the fake backend; the test fails if a page crashes or asks for something unexpected. */
export const test = base.extend<{ api: FakeApi }>({
  api: async ({ page }, use) => {
    const api = new FakeApi();
    const crashes: string[] = [];
    page.on("pageerror", (e) => crashes.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error" && !m.text().includes("status of 500")) crashes.push(m.text());
    });
    page.on("dialog", (d) => d.accept()); // confirm() prompts say yes
    await api.install(page);
    await use(api);
    expect(crashes, "errors in the page").toEqual([]);
    expect(api.unknown, "requests with no test answer").toEqual([]);
  },
});

export { expect };
