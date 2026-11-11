import { useCallback, useEffect, useRef, useState } from "react";
import { api, Job, waitForJob } from "./api";

const ICONS = {
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6L6 18",
  next: "M5 12h14M13 6l6 6-6 6",
  undo: "M9 14L4 9l5-5M4 9h10.5a5.5 5.5 0 010 11H11",
  folder: "M3 7.5A1.5 1.5 0 014.5 6h4l2 2.5h9A1.5 1.5 0 0121 10v8.5a1.5 1.5 0 01-1.5 1.5h-15A1.5 1.5 0 013 18.5z",
  chevron: "M9 6l6 6-6 6",
  plus: "M12 5v14M5 12h14",
};

/** A small line icon drawn in the text color (one stroke weight everywhere). */
export function Icon({ name, size = 16 }: { name: keyof typeof ICONS; size?: number }) {
  return (
    <svg className={`icon icon-${name}`} viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <path d={ICONS[name]} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** A password-style input with an eye button to show or hide what was typed. */
export function SecretInput({
  id,
  value,
  onChange,
  placeholder,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const [shown, setShown] = useState(false);
  return (
    <span className="secret-input">
      <input
        id={id}
        type={shown ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
      />
      <button
        type="button"
        className="eye"
        onClick={(e) => {
          e.preventDefault(); // inside a <label>, a click would otherwise also focus/toggle the input
          setShown(!shown);
        }}
        title={shown ? "Hide" : "Show"}
        aria-label={shown ? "Hide" : "Show"}
        aria-pressed={shown}
      >
        {shown ? (
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path d="M3 3l18 18M10.6 10.6a2 2 0 002.8 2.8M9.9 5.1A9.8 9.8 0 0112 5c5 0 9 4.5 10 7-.4 1-1.3 2.4-2.6 3.7M6.6 6.6C4.4 8 2.9 10.2 2 12c1 2.5 5 7 10 7 1.7 0 3.3-.5 4.6-1.3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path d="M2 12c1-2.5 5-7 10-7s9 4.5 10 7c-1 2.5-5 7-10 7S3 14.5 2 12z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
            <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
        )}
      </button>
    </span>
  );
}

export function ErrorBox({ error, onClose }: { error: string | null; onClose?: () => void }) {
  if (!error) return null;
  return (
    <div className="error" role="alert">
      <span>{error}</span>
      {onClose && (
        <button className="link" onClick={onClose}>
          Dismiss
        </button>
      )}
    </div>
  );
}

export function JobProgress({ job }: { job: Job | null }) {
  if (!job || (job.status !== "running" && job.status !== "stopping")) return null;
  const stop = () => api.post(`/api/jobs/${job.id}/stop`).catch(() => {});
  return (
    <div className="job">
      <div className="row between">
        <div className="job-msg">{job.message}</div>
        <button className="secondary small danger" onClick={stop} disabled={job.status === "stopping"}>
          {job.status === "stopping" ? "Stopping…" : "Stop"}
        </button>
      </div>
      <div className="bar">
        <div className="bar-fill" style={{ width: `${Math.round(job.progress * 100)}%` }} />
      </div>
    </div>
  );
}

/** Start a background job and track it. Returns [run, job, busy]. */
export function useJob(resume?: {
  project: number;
  kind: string;
  /** What the step does when a job it picked back up finishes (usually what it does after run()). */
  done: (j: Job) => unknown;
  failed: (message: string) => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const alive = useRef(true);
  const resumeRef = useRef(resume);
  resumeRef.current = resume;
  const run = useCallback(async (start: () => Promise<Job>) => {
    const j = await start();
    return waitForJob(j, setJob, () => alive.current);
  }, []);
  // The server keeps running a job after its page is left, so pick it back up when the page returns.
  useEffect(() => {
    alive.current = true;
    let live = true; // this mount only (StrictMode mounts twice in dev)
    if (resume) {
      api
        .get<Job[]>(`/api/jobs?project_id=${resume.project}&kind=${resume.kind}`)
        .then(async (running) => {
          if (!running.length || !live) return;
          const j = await waitForJob(running[0], setJob, () => live);
          await resumeRef.current?.done(j);
        })
        .catch((e) => resumeRef.current?.failed((e as Error).message));
    }
    return () => {
      live = false;
      alive.current = false;
    };
  }, [resume?.project, resume?.kind]);
  return { run, job, busy: job?.status === "running" || job?.status === "stopping" };
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="secondary small"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1200);
      }}
    >
      {done ? "Copied" : label}
    </button>
  );
}

export function Stale({ show, children }: { show: boolean; children: React.ReactNode }) {
  if (!show) return null;
  return <div className="warning">{children}</div>;
}
