import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { ask, fmtTime, parseTime, SourceLink, Turn } from "./api";

type Shown = Turn & { sources?: SourceLink[] };

const STARTERS = [
  "What is this video about, in a few sentences?",
  "Who are the main people in this story?",
  "What happened at the moment I'm watching?",
  "What is still uncertain or disputed?",
];

const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

const words = (t: string) => new Set(norm(t).split(" ").filter(Boolean));

/** The source the model meant by "[Source: X]". It may shorten the title or change a letter, so the
 *  source sharing the most words wins, if it shares most of them. */
export function findSource(name: string, sources: SourceLink[]): SourceLink | undefined {
  const a = words(name);
  let best: SourceLink | undefined;
  let bestScore = 0;
  for (const s of sources) {
    const b = words(s.title);
    const shared = [...a].filter((w) => b.has(w)).length;
    const score = shared / Math.max(1, Math.min(a.size, b.size));
    if (score > bestScore) [best, bestScore] = [s, score];
  }
  return bestScore >= 0.6 ? best : undefined;
}

/** A short name for the chip: the site after the last " - " ("... - Wikipedia"), else the whole title. */
function shortName(title: string): string {
  const i = title.lastIndexOf(" - ");
  return i > 0 && title.length - i > 4 ? title.slice(i + 3) : title;
}

/** Turns "[3:42]" into a button that jumps the video there, and "[Source: X]" into a link to that source. */
function render(text: string, seek: (s: number) => void, sources: SourceLink[] = []): ReactNode[] {
  text = text.replace(/\*\*?([^*\n]+)\*\*?/g, "$1"); // drop Markdown bold/italic stars
  const out: ReactNode[] = [];
  const T = "\\d{1,2}:\\d{1,2}(?::\\d{2})?"; // Gemini sometimes writes "0:0"
  const re = new RegExp(`\\[(${T}(?:\\s*[,;]\\s*${T})*)\\]|\\[Source: ([^\\]]+)\\]`, "g");
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) {
      // "[0:00, 1:34]" becomes two buttons.
      for (const t of m[1].split(/\s*[,;]\s*/)) {
        out.push(
          <button key={`${m.index}-${t}`} className="ts" onClick={() => seek(parseTime(t))} title={`Jump to ${fmtTime(parseTime(t))}`}>
            {fmtTime(parseTime(t))}
          </button>,
        );
      }
    } else {
      // "[Source: A; B]" can name more than one.
      for (const name of m[2].split(/\s*;\s*/)) {
        const src = findSource(name, sources);
        out.push(
          src ? (
            <a key={`${m.index}-${name}`} className="src" href={src.url} target="_blank" rel="noopener noreferrer" title={src.title}>
              <span className="src-name">{shortName(src.title)}</span>
              <span className="visually-hidden"> (opens in a new tab)</span>
            </a>
          ) : (
            <span key={`${m.index}-${name}`} className="src" title={name}>
              <span className="src-name">{shortName(name)}</span>
            </span>
          ),
        );
      }
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Chat({
  videoId,
  seek,
  time,
  onClose,
}: {
  videoId: number;
  seek: (s: number) => void;
  time: () => number | null;
  onClose: () => void;
}) {
  const [turns, setTurns] = useState<Shown[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setTurns([]);
    setError(null);
  }, [videoId]);
  // Braces matter: newer browsers make scrollIntoView return a Promise, which React would call as a cleanup.
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  const send = async (question: string) => {
    question = question.trim();
    if (!question || busy) return;
    setError(null);
    setInput("");
    const history = turns.filter((t) => t.text);
    setTurns([...history, { role: "user", text: question }, { role: "model", text: "" }]);
    setBusy(true);
    let answer = "";
    let sources: SourceLink[] = [];
    const show = () => setTurns([...history, { role: "user", text: question }, { role: "model", text: answer, sources }]);
    try {
      const sent = history.map(({ role, text }) => ({ role, text }));
      await ask(
        { video_id: videoId, question, history: sent, at_s: time() },
        (piece) => {
          answer += piece;
          show();
        },
        (s) => (sources = s),
      );
    } catch (e) {
      setError((e as Error).message);
      if (answer) show();
      else setTurns(history);
      if (!answer) setInput(question);
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(input);
  };

  return (
    <aside className="chat" aria-label="Ask about this video">
      <header>
        <h2>Ask about this video</h2>
        <button className="close" onClick={onClose} aria-label="Close the chat">
          ×
        </button>
      </header>
      <div className="messages" aria-live="polite">
        {turns.length === 0 && (
          <div className="intro">
            <p>Ask anything about this story. Answers come from the video and its sources, with links to the moment.</p>
            {STARTERS.map((s) => (
              <button key={s} className="starter" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`msg ${t.role}`}>
            {t.role === "model" ? (t.text ? render(t.text, seek, t.sources) : <span className="typing">Thinking…</span>) : t.text}
          </div>
        ))}
        {error && <div className="msg error">{error}</div>}
        <div ref={end} />
      </div>
      <form onSubmit={submit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a question…"
          maxLength={500}
          aria-label="Your question"
        />
        <button type="submit" disabled={busy || !input.trim()}>
          Ask
        </button>
      </form>
      <p className="fineprint">AI answers can be wrong. Check the moment in the video.</p>
    </aside>
  );
}
