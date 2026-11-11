// Browser tests for the studio pages. They run against the built UI with a fake backend (mock.ts).
//   cd frontend && npm run test:e2e

import { expect, fixtures, PID, test } from "./mock";

const project = fixtures[`/api/projects/${PID}`];

const STEPS = [
  { key: "script", heading: "Script" },
  { key: "beats", heading: "Beats" },
  { key: "voice", heading: "Voice-over (ElevenLabs)" },
  { key: "images", heading: "Image prompts and images" },
  { key: "assemble", heading: "Assemble the video" },
  { key: "publish", heading: "Publishing pack" },
  { key: "site", heading: "Your video site" },
];

test("home lists every video with its progress", async ({ page, api }) => {
  await page.goto("/#/");
  await expect(page.getByRole("heading", { name: "Your videos" })).toBeVisible();
  for (const p of fixtures["/api/projects"].filter((p: any) => !p.archived)) {
    await expect(page.getByRole("link", { name: p.title })).toBeVisible();
  }
  await expect(page.getByText(`${project.status.script_words} words`).first()).toBeVisible();
  expect(api.sent("GET", "/api/projects")).toHaveLength(1);
});

test("archiving a video sends it to the archive", async ({ page, api }) => {
  api.on("PATCH", `/api/projects/${PID}`, {});
  await page.goto("/#/");
  const card = page.locator(".card", { has: page.getByRole("link", { name: project.title }) });
  await card.getByRole("button", { name: "Archive" }).click();
  await expect.poll(() => api.sent("PATCH", `/api/projects/${PID}`).length).toBe(1);
  expect(api.sent("PATCH", `/api/projects/${PID}`)[0].body).toEqual({ archived: true });
});

test("top navigation reaches every page", async ({ page, api }) => {
  await page.goto("/#/");
  await page.getByRole("link", { name: "New project" }).first().click();
  await expect(page.getByRole("heading", { name: "Find a story" })).toBeVisible();
  await expect(page.getByRole("link", { name: "New project" }).first()).toHaveAttribute("aria-current", "page");
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Projects" }).click();
  await expect(page.getByRole("heading", { name: "Your videos" })).toBeVisible();
  expect(api.unknown).toEqual([]);
});

for (const step of STEPS) {
  test(`the ${step.key} step opens with the project's data`, async ({ page }) => {
    await page.goto(`/#/p/${PID}/${step.key}`);
    await expect(page.getByRole("heading", { name: project.title })).toBeVisible();
    await expect(page.getByRole("heading", { name: step.heading, exact: true })).toBeVisible();
    // The step list shows every step and marks this one.
    const steps = page.getByRole("navigation", { name: "Video steps" });
    await expect(steps.getByRole("link")).toHaveCount(STEPS.length);
    await expect(steps.locator('[aria-current="step"]')).toHaveAttribute("href", `#/p/${PID}/${step.key}`);
  });
}

test("the step list moves between steps", async ({ page }) => {
  await page.goto(`/#/p/${PID}/script`);
  await page.getByRole("navigation", { name: "Video steps" }).getByRole("link", { name: /Voice/ }).click();
  await expect(page.getByRole("heading", { name: "Voice-over (ElevenLabs)" })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`#/p/${PID}/voice$`));
});

test("old links to the prompts step open the images step", async ({ page }) => {
  await page.goto(`/#/p/${PID}/prompts`);
  await expect(page.getByRole("heading", { name: "Image prompts and images" })).toBeVisible();
});

test("editing the script saves it", async ({ page, api }) => {
  const script = fixtures[`/api/projects/${PID}/script`];
  api.on("PUT", `/api/projects/${PID}/script`, (c) => ({ ...script, text: c.body.text }));
  await page.goto(`/#/p/${PID}/script`);
  const box = page.locator("textarea.script-text");
  await expect(box).toHaveValue(script.text);
  await box.press("End");
  await box.pressSequentially(" Added line.");
  await expect.poll(() => api.sent("PUT", `/api/projects/${PID}/script`).length, { timeout: 8000 }).toBeGreaterThan(0);
  expect(api.sent("PUT", `/api/projects/${PID}/script`)[0].body.text).toContain("Added line.");
});

test("the script chat drawer opens and closes", async ({ page }) => {
  await page.goto(`/#/p/${PID}/script`);
  await page.getByRole("button", { name: /Ask Claude/ }).first().click();
  const drawer = page.locator(".chat.drawer");
  await expect(drawer).toHaveClass(/open/);
  await expect(drawer.getByRole("heading", { name: "Ask Claude to change the script" })).toBeVisible();
  await drawer.getByRole("button", { name: /Close/ }).click();
  await expect(drawer).not.toHaveClass(/open/);
});

test("your own idea is added to the list", async ({ page, api }) => {
  const idea = { id: 99, project_id: null, title: "The Great Molasses Flood", hook: "A wave of syrup", why_it_works: "", category: "", era: "", documentation: "", source: "own", saved: 0, format: "story" };
  api.on("POST", "/api/ideas/own", idea);
  await page.goto("/#/ideas");
  await page.getByRole("button", { name: "Use my own idea" }).click();
  await page.getByLabel("Your idea").fill("The Great Molasses Flood");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect.poll(() => api.sent("POST", "/api/ideas/own").length).toBe(1);
  expect(api.sent("POST", "/api/ideas/own")[0].body).toMatchObject({ text: "The Great Molasses Flood" });
  await expect(page.getByRole("heading", { name: "The Great Molasses Flood" })).toBeVisible();
});

test("a long job shows progress and can be stopped", async ({ page, api }) => {
  const running = { id: "j1", kind: "suggest", status: "running", message: "Looking for stories", progress: 0.4, result: null, error: null };
  api.on("POST", "/api/ideas/suggest", running);
  api.on("GET", "/api/jobs/j1", () => (api.sent("POST", "/api/jobs/j1/stop").length ? { ...running, status: "stopped" } : running));
  api.on("POST", "/api/jobs/j1/stop", {});
  await page.goto("/#/ideas");
  await page.getByRole("button", { name: "Suggest 3 ideas" }).click();
  await expect(page.getByText("Looking for stories")).toBeVisible();
  expect(api.sent("POST", "/api/ideas/suggest")[0].body).toMatchObject({ count: 3 });
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByText(/Stopped\. You can start it again/)).toBeVisible();
});

test("settings save through the API, keys stay hidden", async ({ page, api }) => {
  api.on("PUT", "/api/settings/config", (c) => c.body);
  await page.goto("/#/settings");
  await expect(page.getByRole("heading", { name: "API keys" })).toBeVisible();
  for (const name of ["Claude", "Research sources", "Script and beats", "Voice", "Pictures and video", "Publishing and Shorts"])
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await expect(page.getByLabel("ElevenLabs API key")).toHaveAttribute("type", "password");
  for (const input of await page.locator(".secret-input input").all()) await expect(input).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect.poll(() => api.sent("PUT", "/api/settings/config").length).toBe(1);
});

test("pages fit a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/#/", "/#/ideas", "/#/settings", `/#/p/${PID}/script`, `/#/p/${PID}/images`]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const extra = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(extra, `${path} scrolls sideways`).toBeLessThanOrEqual(1);
  }
});
