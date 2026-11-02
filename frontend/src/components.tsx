import { useCallback, useEffect, useRef, useState } from "react";
import { api, Job, waitForJob } from "./api";

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
  if (!job || job.status !== "running") return null;
  return (
    <div className="job">
      <div className="job-msg">{job.message}</div>
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
  return { run, job, busy: job?.status === "running" };
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
