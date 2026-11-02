// Thin fetch wrapper around the FastAPI backend.

export class ApiError extends Error {}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : text;
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  put: <T>(url: string, body?: unknown) => request<T>("PUT", url, body ?? {}),
  patch: <T>(url: string, body?: unknown) => request<T>("PATCH", url, body ?? {}),
  del: <T>(url: string) => request<T>("DELETE", url),
};

export interface Job {
  id: string;
  kind: string;
  status: "running" | "done" | "error";
  message: string;
  progress: number;
  result: unknown;
  error: string | null;
}

/** Poll a background job until it finishes. Once `alive()` is false (the page was left), polling
 * stops and the promise never settles; the job keeps running on the server. */
export async function waitForJob(job: Job, onUpdate: (j: Job) => void, alive: () => boolean = () => true): Promise<Job> {
  let j = job;
  onUpdate(j);
  while (j.status === "running") {
    await new Promise((r) => setTimeout(r, 1000));
    if (!alive()) return new Promise<Job>(() => {});
    j = await api.get<Job>(`/api/jobs/${j.id}`);
    onUpdate(j);
  }
  if (j.status === "error") throw new ApiError(j.error || "Job failed");
  return j;
}

/** POST to an SSE endpoint and call onEvent for each `data:` message. */
export async function streamSSE(url: string, body: unknown, onEvent: (e: Record<string, unknown>) => void): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const t = await res.text();
    const d = safeJson(t) as { detail?: string };
    throw new ApiError(d?.detail || t || `HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

export function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}
