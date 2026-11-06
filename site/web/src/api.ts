export interface Video {
  id: number;
  title: string;
  summary: string;
  description?: string;
  youtube_id: string;
  thumbnail_url: string;
  duration_s: number;
  published_at?: string;
}

export interface SearchHit extends Video {
  moment: { start_s: number; end_s: number; text: string } | null;
}

export interface Turn {
  role: "user" | "model";
  text: string;
}

async function errorText(r: Response): Promise<string> {
  try {
    const j = await r.json();
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* not JSON */
  }
  return r.status === 429 ? "Too many requests. Please try again later." : "Something went wrong. Please try again.";
}

export async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await errorText(r));
  return r.json();
}

/** Ask the chatbot; calls onText for each piece of the answer as it streams in. */
export async function ask(
  body: { video_id: number; question: string; history: Turn[]; at_s: number | null },
  onText: (t: string) => void,
): Promise<void> {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok || !r.body) throw new Error(await errorText(r));
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 2);
      if (!line.startsWith("data:")) continue;
      const e = JSON.parse(line.slice(5));
      if (e.type === "text") onText(e.text);
      else if (e.type === "error") throw new Error(e.error);
    }
  }
}

export function fmtTime(s: number): string {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** "3:42" or "1:02:03" -> seconds. */
export function parseTime(t: string): number {
  return t.split(":").reduce((acc, p) => acc * 60 + Number(p), 0);
}
