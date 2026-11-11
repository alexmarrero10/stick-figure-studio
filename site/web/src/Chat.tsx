import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { ask, fmtTime, parseTime, Turn } from "./api";

const STARTERS = [
  "What is this video about, in a few sentences?",
  "Who are the main people in this story?",
  "What happened at the moment I'm watching?",
  "What is still uncertain or disputed?",
];

/** Turns "[3:42]" into a button that jumps the video there, and "[Source: X]" into a small label. */
function render(text: string, seek: (s: number) => void): ReactNode[] {
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
      out.push(
        <span key={m.index} className="src">
          {m[2]}
        </span>,
      );
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
  const [turns, setTurns] = useState<Turn[]>([]);
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
    try {
      await ask({ video_id: videoId, question, history, at_s: time() }, (piece) => {
        answer += piece;
        setTurns([...history, { role: "user", text: question }, { role: "model", text: answer }]);
      });
    } catch (e) {
      setError((e as Error).message);
      setTurns(answer ? [...history, { role: "user", text: question }, { role: "model", text: answer }] : history);
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
            {t.role === "model" ? (t.text ? render(t.text, seek) : <span className="typing">Thinking…</span>) : t.text}
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
