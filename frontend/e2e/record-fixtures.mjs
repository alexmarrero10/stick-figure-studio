// Saves the studio's API answers for one project as test data (e2e/fixtures.json).
// Read-only: it only sends GET requests to the running studio. Long lists are trimmed and
// API keys are replaced with fake ones, so the file is safe to commit.
//
//   node e2e/record-fixtures.mjs [project id]      (studio must be running on port 8765)

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const BASE = "http://127.0.0.1:8765";
const pid = Number(process.argv[2] || 1);
const KEEP = 12; // items kept from long lists
const ROOT = fileURLToPath(new URL("../..", import.meta.url)).replace(/[\\/]$/, "");

const paths = [
  "/api/projects",
  "/api/ideas?saved=true",
  "/api/settings",
  "/api/settings/health",
  "/api/settings/voices",
  `/api/projects/${pid}`,
  `/api/projects/${pid}/research`,
  `/api/projects/${pid}/sources`,
  `/api/projects/${pid}/script`,
  `/api/projects/${pid}/script/versions`,
  `/api/projects/${pid}/script/chat`,
  `/api/projects/${pid}/beats`,
  `/api/projects/${pid}/beats/undo`,
  `/api/projects/${pid}/voice`,
  `/api/projects/${pid}/voice/preview`,
  `/api/projects/${pid}/prompts`,
  `/api/projects/${pid}/images`,
  `/api/projects/${pid}/shots/preview`,
  `/api/projects/${pid}/outputs`,
  `/api/projects/${pid}/publish`,
  `/api/projects/${pid}/site`,
];

/** Shorten every long array (beats, prompts, words...) so the file stays small. */
function trim(v) {
  if (Array.isArray(v)) return v.slice(0, KEEP).map(trim);
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, trim(x)]));
  if (typeof v === "string") {
    v = v.split(ROOT).join("C:\\studio"); // no local folder names
    return v.length > 1500 ? v.slice(0, 1500) + "…" : v;
  }
  return v;
}

const out = {};
for (const p of paths) {
  const res = await fetch(BASE + p);
  if (!res.ok) throw new Error(`${p}: HTTP ${res.status}`);
  out[p] = trim(await res.json());
}
// Never store real keys: keep only whether each one is set.
const keys = out["/api/settings"].keys;
for (const k of Object.keys(keys)) keys[k] = keys[k] ? "test…1234" : null;

const file = new URL("./fixtures.json", import.meta.url);
writeFileSync(file, JSON.stringify(out, null, 1));
console.log(`Saved ${paths.length} answers for project ${pid} to e2e/fixtures.json`);
