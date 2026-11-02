import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox } from "../components";
import { Settings } from "../types";
import SocialAccounts from "./SocialAccounts";

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
  { section: "claude", key: "code_model", label: "Claude Code model", help: "opus or sonnet" },
  { section: "claude", key: "model", label: "API model", help: "Only used with the API provider" },
  { section: "claude", key: "effort", label: "Claude effort", help: "low, medium, high, xhigh or max" },
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
  { section: "voice", key: "trim_pauses", label: "Trim long pauses", type: "bool" },
  { section: "voice", key: "max_pause_s", label: "Longest pause kept (s)", type: "number" },
  { section: "prompts", key: "batch_size", label: "Prompts per batch", type: "number" },
  { section: "shots", key: "cut_lead_s", label: "Cut lead (s)", help: "Picture appears this long before its first word", type: "number" },
  { section: "shots", key: "min_shot_s", label: "Shortest shot (s)", type: "number", help: "Shorter pictures merge into a neighbour" },
  { section: "video", key: "fps", label: "Frame rate", type: "number" },
  { section: "video", key: "crf", label: "MP4 quality (CRF, lower = better)", type: "number" },
  {
    section: "publish",
    key: "general_tags",
    label: "General tags added to every video",
    type: "list",
    help: "Comma separated, e.g. animation, history, education",
  },
  { section: "shorts", key: "channel_name", label: "Channel name on Shorts", help: "Just the name, e.g. NextDoorHistorian; the @ is added under the video" },
  { section: "shorts", key: "max_seconds", label: "Short length (s)", type: "number", help: "It cuts off abruptly here" },
  {
    section: "social",
    key: "youtube_privacy",
    label: "YouTube Short visibility",
    type: "select",
    options: [
      { value: "public", label: "Public" },
      { value: "unlisted", label: "Unlisted" },
      { value: "private", label: "Private" },
    ],
  },
  {
    section: "social",
    key: "tiktok_privacy",
    label: "TikTok visibility",
    type: "select",
    options: [
      { value: "PUBLIC_TO_EVERYONE", label: "Everyone" },
      { value: "FOLLOWER_OF_CREATOR", label: "Followers" },
      { value: "MUTUAL_FOLLOW_FRIENDS", label: "Friends" },
      { value: "SELF_ONLY", label: "Only me" },
    ],
    help: "Until TikTok approves your app, only Only me works",
  },
];

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [keys, setKeys] = useState({ ANTHROPIC_API_KEY: "", ELEVENLABS_API_KEY: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Settings>("/api/settings").then(setS).catch((e) => setError(e.message));
  }, []);

  if (!s) return <ErrorBox error={error} />;

  const setField = (section: string, key: string, value: unknown) =>
    setS({ ...s, config: { ...s.config, [section]: { ...s.config[section], [key]: value } } });

  const saveConfig = async () => {
    setError(null);
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
      await api.put("/api/settings/config", cfg);
      setMsg("Settings saved.");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const saveKey = async (name: keyof typeof keys) => {
    if (!keys[name].trim()) return;
    await api.put("/api/settings/key", { name, value: keys[name] });
    setKeys({ ...keys, [name]: "" });
    setS(await api.get<Settings>("/api/settings"));
    setMsg(`${name} saved to .env`);
  };

  return (
    <div className="settings">
      <h1>Settings</h1>
      {msg && <div className="ok">{msg}</div>}
      <ErrorBox error={error} />
      <div className="panel">
        <h2>API keys</h2>
        <p className="muted small">
          Stored in the .env file in the app folder. The Anthropic key is only needed if the Claude provider is set
          to "Anthropic API"; with Claude Code, your Claude login is used instead.
        </p>
        {(Object.keys(keys) as (keyof typeof keys)[]).map((name) => (
          <div className="row" key={name}>
            <label className="grow">
              {name} <span className="muted">{s.keys[name] ? `(current: ${s.keys[name]})` : "(not set)"}</span>
              <input
                type="password"
                value={keys[name]}
                onChange={(e) => setKeys({ ...keys, [name]: e.target.value })}
                placeholder="Paste a new key"
              />
            </label>
            <button onClick={() => saveKey(name)}>Save</button>
          </div>
        ))}
      </div>
      <SocialAccounts />
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
        <button onClick={saveConfig}>Save settings</button>
      </div>
    </div>
  );
}
