import { useEffect, useRef, useState } from "react";
import { api, fmtTime, streamSSE } from "../api";
import { StepProps } from "../App";
import { findTells } from "../aiTells";
import { ErrorBox, JobProgress, useJob } from "../components";
import { ChatMessage, Edit, FORMAT_LABELS, ScriptVersion, VideoFormat } from "../types";

const FORMAT_HELP: Record<VideoFormat, string> = {
  story: "One true story, followed from start to finish.",
  topic: "A historical subject or question explained through real events, e.g. how Blitzkrieg worked.",
  list: "A countdown of several separate true cases, e.g. the top 5 Navy pilot UFO encounters.",
};

interface Research {
  id: number;
  content: string;
  sources: { title: string; url: string }[];
}

interface VersionRow {
  id: number;
  source: string;
  instruction: string | null;
  word_count: number;
  created_at: string;
}


export default function ScriptStep({ project, refresh }: StepProps) {
  const pid = project.id;
  const [research, setResearch] = useState<Research | null>(null);
  const [briefOpen, setBriefOpen] = useState(false);
  const [brief, setBrief] = useState("");
  const [text, setText] = useState("");
  const [saved, setSaved] = useState("");
  const [notes, setNotes] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [WPM, setWpm] = useState(180);
  const [TARGET, setTarget] = useState([1550, 1650]);
  const [suggest, setSuggest] = useState<{ text: string } | null>(null);
  const { run, job, busy } = useJob({ project: pid, kind: "research", done: () => afterResearch(), failed: (m) => setError(m) });

  const load = async () => {
    const [r, s, v] = await Promise.all([
      api.get<Research | null>(`/api/projects/${pid}/research`),
      api.get<ScriptVersion | null>(`/api/projects/${pid}/script`),
      api.get<VersionRow[]>(`/api/projects/${pid}/script/versions`),
    ]);
    setResearch(r);
    setBrief(r?.content || "");
    setBriefOpen(!s && !!r);
    setText(s?.text || "");
    setSaved(s?.text || "");
    setVersions(v);
  };
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [pid]);
  useEffect(() => {
    api
      .get<{ config: { script: { wpm_estimate: number; target_words_min: number; target_words_max: number } } }>("/api/settings")
      .then(({ config: { script } }) => {
        setWpm(script.wpm_estimate);
        setTarget([script.target_words_min, script.target_words_max]);
      })
      .catch(() => {});
  }, []);

  // Autosave 4 s after typing stops.
  useEffect(() => {
    if (streaming || text === saved || !text.trim()) return;
    const t = setTimeout(() => save(), 4000);
    return () => clearTimeout(t);
  }, [text, saved, streaming]);

  const save = async () => {
    try {
      await api.put(`/api/projects/${pid}/script`, { text, source: "manual" });
      setSaved(text);
      setVersions(await api.get<VersionRow[]>(`/api/projects/${pid}/script/versions`));
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const afterResearch = async () => {
    await load();
    setBriefOpen(true);
    refresh();
  };

  const doResearch = async () => {
    setError(null);
    try {
      await run(() => api.post(`/api/projects/${pid}/research`));
      await afterResearch();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const setFormat = async (format: VideoFormat) => {
    setError(null);
    try {
      await api.patch(`/api/projects/${pid}`, { format });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const saveBrief = async () => {
    const r = await api.put<Research>(`/api/projects/${pid}/research`, { content: brief });
    setResearch(r);
  };

  const generate = async () => {
    if (text.trim() && !window.confirm("Write a new script? The current one stays in version history.")) return;
    setError(null);
    setStreaming(true);
    setText("");
    let acc = "";
    try {
      await streamSSE(`/api/projects/${pid}/script/generate`, { notes }, (e) => {
        if (e.type === "text") {
          acc += e.text as string;
          setText(acc);
        } else if (e.type === "done") {
          const v = e.version as ScriptVersion;
          setText(v.text);
          setSaved(v.text);
        } else if (e.type === "error") {
          setError(e.error as string);
        }
      });
      setVersions(await api.get<VersionRow[]>(`/api/projects/${pid}/script/versions`));
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStreaming(false);
    }
  };

  const restore = async (id: number) => {
    const v = await api.post<ScriptVersion>(`/api/projects/${pid}/script/versions/${id}/restore`);
    setText(v.text);
    setSaved(v.text);
    setVersions(await api.get<VersionRow[]>(`/api/projects/${pid}/script/versions`));
    refresh();
  };

  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const runtime = (words / WPM) * 60;
  const lengthClass = words < TARGET[0] * 0.9 ? "warn" : words > TARGET[1] * 1.1 ? "warn" : "good";
  const tells = streaming ? [] : findTells(saved);
  const tellList = tells.map((t) => `"${t.label}"${t.count > 1 ? ` (${t.count}x)` : ""}`).join(", ");

  return (
    <div className="script-step">
      <ErrorBox error={error} onClose={() => setError(null)} />

      <div className="panel">
        <div className="row between">
          <h2>Research brief</h2>
          <div className="row">
            {research && (
              <button className="secondary small" onClick={() => setBriefOpen(!briefOpen)}>
                {briefOpen ? "Hide" : "Show"}
              </button>
            )}
            <button onClick={doResearch} disabled={busy}>
              {research ? "Research again" : "Research"}
            </button>
          </div>
        </div>
        <div className="row format-row">
          <label className="inline">
            Video type
            <select value={project.format} onChange={(e) => setFormat(e.target.value as VideoFormat)}>
              {(Object.keys(FORMAT_LABELS) as VideoFormat[]).map((f) => (
                <option key={f} value={f}>
                  {FORMAT_LABELS[f]}
                </option>
              ))}
            </select>
          </label>
          <span className="muted small">{FORMAT_HELP[project.format] ?? ""}</span>
        </div>
        <p className="muted small">
          Claude searches the web and gathers facts, dates, people, and what is disputed, before writing. Every fact
          is tied to a source, dead links are dropped, and the sources go into the video's description on the
          Publish step. Check the brief for accuracy and edit anything wrong, then write the script. Change the video
          type before researching.
        </p>
        <JobProgress job={job} />
        {research && briefOpen && (
          <>
            <textarea className="brief" rows={16} value={brief} onChange={(e) => setBrief(e.target.value)} />
            <div className="row between">
              <button className="secondary small" onClick={saveBrief} disabled={brief === research.content}>
                Save brief edits
              </button>
              <span className="muted small">{research.sources.length} web sources</span>
            </div>
            {research.sources.length > 0 && (
              <details>
                <summary>Sources</summary>
                <ul className="sources">
                  {research.sources.map((s) => (
                    <li key={s.url}>
                      <a href={s.url} target="_blank" rel="noreferrer">
                        {s.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </div>

      <div className="script-layout">
        <div className="panel editor">
          <div className="row between">
            <h2>Script</h2>
            <div className={`meter ${lengthClass}`}>
              {words} words · ~{fmtTime(runtime)} (target {TARGET[0]}-{TARGET[1]})
            </div>
          </div>
          <div className="row">
            <input
              className="grow"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional notes for Claude (tone, angle, things to include)"
            />
            <button onClick={generate} disabled={!research || streaming}>
              {streaming ? "Writing…" : text ? "Rewrite script" : "Write script"}
            </button>
          </div>
          <textarea
            className="script-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            readOnly={streaming}
            placeholder={research ? "Click 'Write script', or write your own." : "Run the research step first."}
          />
          {tells.length > 0 && (
            <div className="warning small">
              <span>Sounds machine-written: {tellList}.</span>{" "}
              <button
                className="link"
                onClick={() =>
                  setSuggest({
                    text:
                      `Rewrite only the sentences that use these phrases or patterns so they sound like a real person ` +
                      `telling the story: ${tellList}. Keep the facts, the meaning and the length the same.`,
                  })
                }
              >
                Ask Claude to fix them
              </button>
            </div>
          )}
          <div className="row between">
            <span className="muted small">
              {streaming ? "Streaming…" : text === saved ? "All changes saved" : "Unsaved changes (autosaves)"}
            </span>
            <div className="row">
              <select onChange={(e) => e.target.value && restore(Number(e.target.value))} value="">
                <option value="">Version history ({versions.length})</option>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    #{v.id} · {v.source} · {v.word_count} words · {v.created_at}
                    {v.instruction ? ` · ${v.instruction.slice(0, 40)}` : ""}
                  </option>
                ))}
              </select>
              <button onClick={save} disabled={text === saved || streaming}>
                Save
              </button>
              <a className="button" href={`#/p/${pid}/beats`}>
                Next: beats →
              </a>
            </div>
          </div>
        </div>
        <Chat pid={pid} suggest={suggest} disabled={!saved || streaming || text !== saved} onApplied={(t) => { setText(t); setSaved(t); refresh(); api.get<VersionRow[]>(`/api/projects/${pid}/script/versions`).then(setVersions); }} />
      </div>
    </div>
  );
}

function Chat({
  pid,
  disabled,
  onApplied,
  suggest,
}: {
  pid: number;
  disabled: boolean;
  onApplied: (text: string) => void;
  suggest: { text: string } | null; // a request to put in the box, e.g. from "Ask Claude to fix them"
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  useEffect(() => {
    if (suggest) setInput(suggest.text);
  }, [suggest]);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ msgId: number; edits: Edit[]; chosen: boolean[]; instruction: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.get<ChatMessage[]>(`/api/projects/${pid}/script/chat`).then(setMessages).catch(() => {});
  }, [pid]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, pending]);

  const send = async () => {
    if (!input.trim()) return;
    const instruction = input;
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { id: -Date.now(), role: "user", content: instruction, edits: null }]);
    setInput("");
    try {
      const reply = await api.post<ChatMessage>(`/api/projects/${pid}/script/chat`, { message: instruction });
      setMessages((m) => [...m, reply]);
      const edits = reply.edits || [];
      if (edits.length) setPending({ msgId: reply.id, edits, chosen: edits.map((e) => e.ok), instruction });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!pending) return;
    const chosen = pending.edits.filter((_, i) => pending.chosen[i]);
    const res = await api.post<{ version: ScriptVersion; errors: string[] }>(`/api/projects/${pid}/script/apply-edits`, {
      edits: chosen,
      instruction: pending.instruction,
    });
    if (res.errors.length) setError(res.errors.join("\n"));
    setPending(null);
    onApplied(res.version.text);
  };

  return (
    <div className="panel chat">
      <h2>Ask Claude to change the script</h2>
      <div className="messages">
        {messages.length === 0 && (
          <p className="muted small">
            e.g. "Make the hook more shocking", "Cut the second paragraph by half", "Add a re-hook before the
            bank scene", "Is the date in paragraph 3 right?"
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            {m.content}
          </div>
        ))}
        {pending && (
          <div className="edits">
            {pending.edits.map((e, i) => (
              <label key={i} className={`edit ${e.ok ? "" : "bad"}`}>
                <input
                  type="checkbox"
                  disabled={!e.ok}
                  checked={pending.chosen[i]}
                  onChange={(ev) =>
                    setPending({ ...pending, chosen: pending.chosen.map((c, k) => (k === i ? ev.target.checked : c)) })
                  }
                />
                <div>
                  <del>{e.find}</del>
                  <ins>{e.replace || "(deleted)"}</ins>
                  <small className="muted">{e.ok ? e.reason : `Can't apply: ${e.error}`}</small>
                </div>
              </label>
            ))}
            <div className="row">
              <button onClick={apply} disabled={!pending.chosen.some(Boolean)}>
                Apply selected
              </button>
              <button className="secondary" onClick={() => setPending(null)}>
                Discard
              </button>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div className="row">
        <textarea
          className="grow"
          rows={2}
          value={input}
          disabled={disabled || busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder={disabled ? "Save the script first" : "Type a change and press Enter"}
        />
        <button onClick={send} disabled={disabled || busy || !input.trim()}>
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
