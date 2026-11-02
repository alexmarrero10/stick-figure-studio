import { useEffect, useRef, useState } from "react";
import { api, fmtTime } from "../api";
import { StepProps } from "../App";
import { ErrorBox, JobProgress, Stale, useJob } from "../components";
import { Beat } from "../types";

interface Voice {
  duration_s: number;
  warnings: string[];
  audio_url: string | null;
  stale: boolean;
  word_count: number;
  chars: number;
  created_at: string;
}

export default function VoiceStep({ project, refresh }: StepProps) {
  const pid = project.id;
  const [voice, setVoice] = useState<Voice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bust, setBust] = useState(0);
  const { run, job, busy } = useJob({ project: pid, kind: "voice", done: () => afterVoice(), failed: (m) => setError(m) });

  const load = () => api.get<Voice | null>(`/api/projects/${pid}/voice`).then(setVoice);
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [pid]);

  const afterVoice = async () => {
    await load();
    setBust(Date.now());
    refresh();
  };

  const generate = async () => {
    if (voice && !window.confirm("Generate the voice-over again? This uses ElevenLabs credits.")) return;
    setError(null);
    try {
      await run(() => api.post(`/api/projects/${pid}/voice`));
      await afterVoice();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const s = project.status;
  return (
    <div>
    <Preview pid={pid} disabled={busy || !s.script} />
    <div className="panel">
      <h2>Voice-over (ElevenLabs)</h2>
      <p className="muted small">
        Sends the current script to ElevenLabs with timestamps. Every word gets a start and end time, and long pauses are
        trimmed so there is little dead air. About {s.script_words} words, roughly{" "}
        {Math.round((s.script_words * 6.1) / 1000)}k characters of credits.
      </p>
      <Stale show={!!voice?.stale}>The script changed after this voice-over was made. Generate it again.</Stale>
      <Stale show={s.beats_stale || (!s.beats && s.script)}>Build (or rebuild) the beats before or after this step.</Stale>
      <div className="row">
        <button onClick={generate} disabled={busy || !s.script}>
          {busy ? "Generating…" : voice ? "Regenerate voice-over" : "Generate voice-over"}
        </button>
        {voice && (
          <a className="button" href={`#/p/${pid}/images`}>
            Next: images →
          </a>
        )}
      </div>
      <JobProgress job={job} />
      <ErrorBox error={error} onClose={() => setError(null)} />
      {voice && (
        <div className="voice-result">
          {voice.audio_url && <ScriptFollow pid={pid} src={`${voice.audio_url}&t=${bust}`} reload={bust} />}
          <p>
            Length <strong>{fmtTime(voice.duration_s)}</strong> · {voice.word_count} timed words · made {voice.created_at}
          </p>
          {voice.duration_s < 480 && <div className="warning">Under 8 minutes. YouTube allows mid-roll ads from 8:00, so consider lengthening the script.</div>}
          {voice.warnings.map((w) => (
            <div key={w} className="warning small">
              {w}
            </div>
          ))}
        </div>
      )}
    </div>
    </div>
  );
}

/** The voice-over player with the script laid out beat by beat; the beat being spoken is highlighted. */
function ScriptFollow({ pid, src, reload }: { pid: number; src: string; reload: number }) {
  const audio = useRef<HTMLAudioElement>(null);
  const list = useRef<HTMLOListElement>(null);
  const [beats, setBeats] = useState<Beat[]>([]);
  const [now, setNow] = useState(0);
  const [follow, setFollow] = useState(true);

  useEffect(() => {
    api.get<Beat[]>(`/api/projects/${pid}/beats`).then(setBeats).catch(() => {});
  }, [pid, reload]);

  const timed = beats.length > 0 && beats.every((b) => b.start !== undefined);
  // The current beat is the last one that has started; gaps between beats keep the previous one lit.
  let current = -1;
  if (timed) for (const b of beats) if (b.start! <= now + 0.05) current = b.idx;

  useEffect(() => {
    if (!follow || current < 0 || !list.current || audio.current?.paused) return;
    const el = list.current.querySelector<HTMLElement>(`[data-idx="${current}"]`);
    if (!el) return;
    const box = list.current;
    box.scrollTo({ top: el.offsetTop - box.clientHeight / 3, behavior: "smooth" });
  }, [current, follow]);

  const seek = (b: Beat) => {
    if (!audio.current || b.start === undefined) return;
    audio.current.currentTime = b.start;
    audio.current.play().catch(() => {});
  };

  return (
    <div className="follow">
      <audio ref={audio} controls src={src} onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)} onSeeked={(e) => setNow(e.currentTarget.currentTime)} />
      {beats.length > 0 && (
        <>
          <div className="row between">
            <strong>Script by beat</strong>
            {timed ? (
              <label className="check small">
                <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
                Scroll along with the voice
              </label>
            ) : (
              <span className="muted small">The beats don't match this voice-over, so they can't follow along. Rebuild the beats or regenerate the voice.</span>
            )}
          </div>
          <ol className="follow-list" ref={list}>
            {beats.map((b) => (
              <li
                key={b.id}
                data-idx={b.idx}
                className={`${b.idx === current ? "now" : ""} ${timed ? "timed" : ""}`}
                onClick={() => seek(b)}
                title={timed ? "Play from here" : undefined}
              >
                <span className="muted small">
                  #{b.idx}
                  {b.start !== undefined && ` · ${fmtTime(b.start)}`}
                </span>
                <span>{b.text}</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

interface PreviewResult {
  audio_url: string;
  text?: string;
  chars?: number;
  duration?: number;
  model_id?: string;
  voice_id?: string;
}

interface VoiceOption {
  voice_id: string;
  name: string;
  use_case: string;
}

const MODELS = [
  { value: "eleven_v4", label: "Eleven v4 (best quality)" },
  { value: "eleven_multilingual_v2", label: "Multilingual v2 (older)" },
];

const SLIDERS = [
  { key: "stability", label: "Stability", hint: "Lower = more emotional range. Too low can sound uneven or strange." },
  { key: "similarity_boost", label: "Similarity", hint: "Higher = closer to the original voice." },
  { key: "style", label: "Style (energy)", hint: "Multilingual v2 only. High values can sound overacted." },
] as const;
type SliderKey = (typeof SLIDERS)[number]["key"];
type Vals = Record<SliderKey, number> & { model_id: string; voice_id: string };

function Preview({ pid, disabled }: { pid: number; disabled: boolean }) {
  const [saved, setSaved] = useState<Vals | null>(null);
  const [vals, setVals] = useState<Vals>({ stability: 0.5, similarity_boost: 0.9, style: 0, model_id: "eleven_v4", voice_id: "" });
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [seconds, setSeconds] = useState(30);
  const [result, setResult] = useState<PreviewResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<{ config: { voice: Vals } }>("/api/settings")
      .then(({ config: { voice } }) => {
        const v = {
          stability: voice.stability,
          similarity_boost: voice.similarity_boost,
          style: voice.style,
          model_id: voice.model_id,
          voice_id: voice.voice_id,
        };
        setSaved(v);
        setVals(v);
      })
      .catch(() => {});
    api.get<PreviewResult | null>(`/api/projects/${pid}/voice/preview`).then(setResult).catch(() => {});
    api.get<VoiceOption[]>("/api/settings/voices").then(setVoices).catch(() => {});
  }, [pid]);

  const make = async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      setResult(await api.post<PreviewResult>(`/api/projects/${pid}/voice/preview`, { seconds, ...vals }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const keep = async () => {
    try {
      const name = voices.find((v) => v.voice_id === vals.voice_id)?.name.split(" - ")[0].trim();
      await api.put("/api/settings/config", { voice: { ...vals, ...(name ? { voice_name: name } : {}) } });
      setSaved(vals);
      setNote("Saved. The full voice-over will use these settings.");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const changed = saved !== null && (["model_id", "voice_id", ...SLIDERS.map((x) => x.key)] as const).some((k) => saved[k] !== vals[k]);
  const hasStyle = !vals.model_id.startsWith("eleven_v4") && !vals.model_id.startsWith("eleven_v3");

  return (
    <div className="panel">
      <h2>Preview the voice</h2>
      <p className="muted small">
        Voices just the opening of the script (about {seconds} seconds, roughly {Math.round(seconds * 3 * 6.1)}{" "}
        characters of credits) so you can try the tone before generating the whole thing.
      </p>
      <div className="sliders">
        {voices.length > 0 && (
          <label>
            <span>
              Voice
              {saved && saved.voice_id !== vals.voice_id && (
                <span className="muted"> (saved {voices.find((v) => v.voice_id === saved.voice_id)?.name ?? saved.voice_id})</span>
              )}
            </span>
            <select value={vals.voice_id} onChange={(e) => setVals({ ...vals, voice_id: e.target.value })}>
              {!voices.some((v) => v.voice_id === vals.voice_id) && <option value={vals.voice_id}>{vals.voice_id}</option>}
              {voices.map((v) => (
                <option key={v.voice_id} value={v.voice_id}>
                  {v.name}
                  {v.use_case ? ` (${v.use_case.replace(/_/g, " ")})` : ""}
                </option>
              ))}
            </select>
            <span className="muted small">Add more voices to your account from the ElevenLabs Voice Library.</span>
          </label>
        )}
        <label>
          <span>
            Model
            {saved && saved.model_id !== vals.model_id && <span className="muted"> (saved {saved.model_id})</span>}
          </span>
          <select value={vals.model_id} onChange={(e) => setVals({ ...vals, model_id: e.target.value })}>
            {MODELS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        {SLIDERS.filter(({ key }) => key !== "style" || hasStyle).map(({ key, label, hint }) => (
          <label key={key} title={hint}>
            <span>
              {label}: <strong>{vals[key].toFixed(2)}</strong>
              {saved && saved[key] !== vals[key] && <span className="muted"> (saved {saved[key].toFixed(2)})</span>}
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={vals[key]}
              onChange={(e) => setVals({ ...vals, [key]: Number(e.target.value) })}
            />
            <span className="muted small">{hint}</span>
          </label>
        ))}
        <label>
          <span>Length</span>
          <select value={seconds} onChange={(e) => setSeconds(Number(e.target.value))}>
            {[15, 30, 45, 60].map((n) => (
              <option key={n} value={n}>
                ~{n} seconds
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="row">
        <button onClick={make} disabled={disabled || busy}>
          {busy ? "Generating preview…" : result ? "New preview" : "Generate preview"}
        </button>
        {changed && (
          <button className="secondary" onClick={keep}>
            Use these settings for the full voice-over
          </button>
        )}
      </div>
      <ErrorBox error={error} onClose={() => setError(null)} />
      {note && <div className="ok">{note}</div>}
      {result && (
        <div className="voice-result">
          <audio controls autoPlay={!!result.text} src={result.audio_url} />
          {result.duration !== undefined && (
            <p className="muted small">
              {fmtTime(result.duration)} · {result.chars} characters{result.model_id ? ` · ${result.model_id}` : ""}
              {result.voice_id ? ` · ${voices.find((v) => v.voice_id === result.voice_id)?.name ?? result.voice_id}` : ""}
            </p>
          )}
          {result.text && (
            <details>
              <summary className="small">Text that was read</summary>
              <p className="small">{result.text}</p>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
