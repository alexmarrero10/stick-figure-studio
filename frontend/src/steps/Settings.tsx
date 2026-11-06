import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, SecretInput } from "../components";
import { Settings } from "../types";

const FIELDS: {
  section: string;
  key: string;
  label: string;
  help?: string;
  type?: "number" | "bool" | "text" | "select" | "list";
  options?: { value: string; label: string }[];
}[] = [
  {
    section: "claude",
    key: "provider",
    label: "Claude provider",
    type: "select",
    options: [
      { value: "claude_code", label: "Claude Code (your Claude subscription)" },
      { value: "api", label: "Anthropic API (API key, pay as you go)" },
    ],
    help: "Claude Code uses your Pro/Max login and counts against its usage limits",
  },
  {
    section: "claude",
    key: "code_model",
    label: "Claude Code model",
    type: "select",
    options: [
      { value: "fable", label: "Fable (most capable, uses the most of your limits)" },
      { value: "opus", label: "Opus (recommended)" },
      { value: "sonnet", label: "Sonnet (faster, lighter on limits)" },
      { value: "haiku", label: "Haiku (fastest, simplest tasks)" },
    ],
  },
  {
    section: "claude",
    key: "model",
    label: "API model",
    type: "select",
    options: [
      { value: "claude-fable-5-1", label: "Fable 5.1" },
      { value: "claude-opus-5-5", label: "Opus 5.5 (recommended)" },
      { value: "claude-sonnet-5-5", label: "Sonnet 5.5" },
      { value: "claude-haiku-5-5", label: "Haiku 5.5" },
    ],
    help: "Only used with the API provider",
  },
  {
    section: "claude",
    key: "effort",
    label: "Claude effort",
    type: "select",
    options: [
      { value: "low", label: "Low" },
      { value: "medium", label: "Medium" },
      { value: "high", label: "High (recommended)" },
      { value: "xhigh", label: "Extra high" },
      { value: "max", label: "Max (slowest)" },
    ],
    help: "How hard Claude thinks. Higher is better but slower and uses more of your limits",
  },
  { section: "claude", key: "web_search", label: "Web search during research", type: "bool" },
  {
    section: "claude",
    key: "research_depth",
    label: "Research depth",
    type: "select",
    options: [
      { value: "quick", label: "Quick (4-6 sources, a few minutes at most)" },
      { value: "thorough", label: "Thorough (10+ sources, about 5-10 min)" },
    ],
    help: "Quick starts from what Claude already knows and searches only to check the key facts",
  },
  {
    section: "rag",
    key: "enabled",
    label: "Research from downloaded sources",
    type: "bool",
    help: "Downloads 10-15 sources into your Supabase database and writes the brief from them. Needs the Gemini key and Supabase address. Research depth is not used when this is on.",
  },
  { section: "rag", key: "docs_min", label: "Fewest sources to download", type: "number" },
  { section: "rag", key: "docs_max", label: "Most sources to download", type: "number" },
  {
    section: "rag",
    key: "brief_chunks",
    label: "Passages used for the brief",
    type: "number",
    help: "About 300 words each. More gives a fuller brief but uses more of your Claude plan",
  },
  {
    section: "rag",
    key: "script_chunks",
    label: "Passages sent with the script",
    type: "number",
    help: "Extra source detail for fact checking while the script is written",
  },
  {
    section: "rag",
    key: "use_shared",
    label: "Also use sources from other videos",
    type: "bool",
    help: "Close matches from earlier videos' sources can fill gaps",
  },
  { section: "script", key: "target_words_min", label: "Script target: min words", type: "number" },
  { section: "script", key: "target_words_max", label: "Script target: max words", type: "number" },
  { section: "script", key: "wpm_estimate", label: "Narration speed (words/min)", type: "number" },
  { section: "beats", key: "min_words", label: "Beat: min words", type: "number", help: "2 words is about 0.5-0.7 s" },
  { section: "beats", key: "max_words", label: "Beat: max words", type: "number", help: "About 3 words per second; 8 gives a new picture every 0.5-3 s" },
  { section: "voice", key: "voice_id", label: "ElevenLabs voice ID", help: "Josh (Warm, Smooth and Steady) is ZoiZ8fuDWInAcwPXaVeq" },
  {
    section: "voice",
    key: "model_id",
    label: "ElevenLabs model",
    type: "select",
    options: [
      { value: "eleven_v4", label: "Eleven v4 (best quality, recommended)" },
      { value: "eleven_multilingual_v2", label: "Multilingual v2 (older)" },
    ],
  },
  { section: "voice", key: "stability", label: "Voice stability (0-1)", type: "number" },
  { section: "voice", key: "similarity_boost", label: "Voice similarity (0-1)", type: "number" },
  { section: "voice", key: "style", label: "Voice style (0-1)", type: "number", help: "Multilingual v2 only; Eleven v4 ignores it" },
  {
    section: "voice",
    key: "speed",
    label: "Narration speed",
    type: "number",
    help: "1.0 = ElevenLabs' natural pace, 1.1 = 10% faster (pitch stays the same). 0.8-1.3. Applies to new voice-overs and previews",
  },
  { section: "voice", key: "trim_pauses", label: "Trim long pauses", type: "bool" },
  { section: "voice", key: "max_pause_s", label: "Longest pause kept (s)", type: "number" },
  { section: "prompts", key: "batch_size", label: "Prompts per batch", type: "number" },
  { section: "shots", key: "cut_lead_s", label: "Cut lead (s)", help: "Picture appears this long before its first word", type: "number" },
  { section: "shots", key: "min_shot_s", label: "Shortest shot (s)", type: "number", help: "Shorter pictures merge into a neighbour" },
  { section: "video", key: "fps", label: "Frame rate", type: "number" },
  { section: "video", key: "crf", label: "MP4 quality (CRF, lower = better)", type: "number" },
  {
    section: "video",
    key: "zoom_min_seconds",
    label: "Zoom in on shots longer than (s)",
    type: "number",
    help: "Long shots slowly zoom in so the picture doesn't feel frozen",
  },
  {
    section: "video",
    key: "zoom_per_second",
    label: "Zoom speed (per second)",
    type: "number",
    help: "0.015 = 1.5% closer each second, up to 12%. 0 turns zoom off",
  },
  {
    section: "publish",
    key: "general_tags",
    label: "General tags added to every video",
    type: "list",
    help: "Comma separated, e.g. animation, history, education",
  },
  { section: "shorts", key: "channel_name", label: "Channel name on the Short", help: "Just the name, e.g. NextDoorHistorian; the @ is added under the video" },
  { section: "shorts", key: "min_seconds", label: "Shortest Short (s)", type: "number", help: "The Short ends on the best cliffhanger between these two lengths" },
  { section: "shorts", key: "max_seconds", label: "Longest Short (s)", type: "number", help: "With no sentence ending in between, it cuts off here" },
];

const KEY_HELP: Record<string, string> = {
  GEMINI_API_KEY: "Free key from aistudio.google.com. Leave billing off on that Google project so it can never cost money.",
  SUPABASE_DB_URL:
    "Supabase: Connect > Session pooler > URI, with your database password filled in. Run backend/supabase/schema.sql once in its SQL Editor.",
  SITE_DATABASE_URL:
    "For the public site only: the same Session pooler URI, but with the user site_reader.<project-ref> and the password you gave it in 002_site_reader.sql.",
};

interface RagCheck {
  enabled: boolean;
  gemini: { ok: boolean; message: string };
  database: { ok: boolean; message: string };
}

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [keys, setKeys] = useState({ ANTHROPIC_API_KEY: "", ELEVENLABS_API_KEY: "", GEMINI_API_KEY: "", SUPABASE_DB_URL: "", SITE_DATABASE_URL: "" });
  const [ragCheck, setRagCheck] = useState<RagCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Result of the last save, shown next to the button that made it.
  const [saved, setSaved] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    api.get<Settings>("/api/settings").then(setS).catch((e) => setError(e.message));
  }, []);

  if (!s) return <ErrorBox error={error} />;

  const setField = (section: string, key: string, value: unknown) =>
    setS({ ...s, config: { ...s.config, [section]: { ...s.config[section], [key]: value } } });

  const report = (where: string, ok: boolean, text: string) => setSaved((r) => ({ ...r, [where]: { ok, text } }));

  const saveConfig = async () => {
    setSaving("config");
    try {
      const cfg: Record<string, Record<string, unknown>> = JSON.parse(JSON.stringify(s.config));
      for (const f of FIELDS) {
        const v = cfg[f.section]?.[f.key];
        if (f.type === "number" && v !== undefined) {
          const n = Number(v);
          if (Number.isNaN(n)) throw new Error(`${f.label} must be a number`);
          cfg[f.section][f.key] = n;
        }
        if (f.section === "shorts" && f.key === "channel_name" && typeof v === "string") {
          cfg[f.section][f.key] = v.trim().replace(/^@+/, "");
        }
        if (f.type === "list" && typeof v === "string") {
          cfg[f.section][f.key] = v.split(",").map((t) => t.trim()).filter(Boolean);
        }
      }
      const stored = await api.put<Settings["config"]>("/api/settings/config", cfg);
      setS({ ...s, config: stored });
      report("config", true, `Settings saved at ${new Date().toLocaleTimeString()}.`);
    } catch (e) {
      report("config", false, `Not saved: ${(e as Error).message}`);
    } finally {
      setSaving(null);
    }
  };

  const saveKey = async (name: keyof typeof keys) => {
    if (!keys[name].trim()) {
      report(name, false, "Paste a key first.");
      return;
    }
    setSaving(name);
    try {
      await api.put("/api/settings/key", { name, value: keys[name] });
      setKeys({ ...keys, [name]: "" });
      setS(await api.get<Settings>("/api/settings"));
      report(name, true, "Saved to .env.");
    } catch (e) {
      report(name, false, `Not saved: ${(e as Error).message}`);
    } finally {
      setSaving(null);
    }
  };

  const testRag = async () => {
    setSaving("rag");
    setRagCheck(null);
    try {
      setRagCheck(await api.post<RagCheck>("/api/settings/rag-check"));
    } catch (e) {
      report("rag", false, (e as Error).message);
    } finally {
      setSaving(null);
    }
  };

  const status = (where: string) =>
    saved[where] && <span className={`save-status ${saved[where].ok ? "good" : "bad"}`}>{saved[where].text}</span>;

  return (
    <div className="settings">
      <h1>Settings</h1>
      <ErrorBox error={error} />
      <div className="panel">
        <h2>API keys</h2>
        <p className="muted small">
          Stored in the .env file in the app folder. The Anthropic key is only needed if the Claude provider is set
          to "Anthropic API"; with Claude Code, your Claude login is used instead. The Gemini key (free, from Google AI
          Studio) and the Supabase database address are for researching from downloaded sources.
        </p>
        {(Object.keys(keys) as (keyof typeof keys)[]).map((name) => (
          <div className="row" key={name}>
            <label className="grow">
              {name} <span className="muted">{s.keys[name] ? `(current: ${s.keys[name]})` : "(not set)"}</span>
              {KEY_HELP[name] && <small className="muted">{KEY_HELP[name]}</small>}
              <SecretInput
                value={keys[name]}
                onChange={(v) => setKeys({ ...keys, [name]: v })}
                placeholder="Paste a new key"
              />
            </label>
            <button onClick={() => saveKey(name)} disabled={saving === name}>
              {saving === name ? "Saving…" : "Save"}
            </button>
            {status(name)}
          </div>
        ))}
        <div className="row">
          <button className="secondary" onClick={testRag} disabled={saving === "rag"}>
            {saving === "rag" ? "Testing…" : "Test Gemini and Supabase"}
          </button>
          {status("rag")}
        </div>
        {ragCheck && (
          <ul className="small">
            {[ragCheck.gemini, ragCheck.database].map((r, i) => (
              <li key={i} className={r.ok ? "good" : "bad"}>
                {r.ok ? "✓" : "✗"} {r.message}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="panel">
        <h2>Pipeline</h2>
        <div className="grid2">
          {FIELDS.map((f) => {
            const v = s.config[f.section]?.[f.key];
            return (
              <label key={`${f.section}.${f.key}`} className={f.type === "bool" ? "check" : ""}>
                {f.type === "select" ? (
                  <>
                    {f.label}
                    <select value={String(v ?? "")} onChange={(e) => setField(f.section, f.key, e.target.value)}>
                      {/* Keep a value set by hand in config.yaml visible even if it isn't a listed choice. */}
                      {v != null && v !== "" && !f.options!.some((o) => o.value === String(v)) && (
                        <option value={String(v)}>{String(v)}</option>
                      )}
                      {f.options!.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </>
                ) : f.type === "bool" ? (
                  <>
                    <input type="checkbox" checked={!!v} onChange={(e) => setField(f.section, f.key, e.target.checked)} />
                    {f.label}
                  </>
                ) : (
                  <>
                    {f.label}
                    <input
                      value={Array.isArray(v) ? v.join(", ") : String(v ?? "")}
                      onChange={(e) => setField(f.section, f.key, e.target.value)}
                    />
                  </>
                )}
                {f.help && <small className="muted">{f.help}</small>}
              </label>
            );
          })}
        </div>
        <div className="row">
          <button onClick={saveConfig} disabled={saving === "config"}>
            {saving === "config" ? "Saving…" : "Save settings"}
          </button>
          {status("config")}
        </div>
      </div>
    </div>
  );
}
