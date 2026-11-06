import { useEffect, useState } from "react";
import { api, fmtTime, Job } from "../api";
import { StepProps } from "../App";
import { ErrorBox, JobProgress, useJob } from "../components";

interface Preview {
  shots: { image: string | null; start_frame: number; end_frame: number; scale: number; beat_ids: number[] }[];
  unused_images: string[];
  missing_images: number[];
  fps: number;
  stats: { shots: number; min_s: number; max_s: number; avg_s: number; total_s: number };
}

interface Outputs {
  folder: string;
  files: Record<string, { url: string; path: string; size: number; modified: number }>;
}

interface AssembleResult {
  duration: number;
  drift_s: number;
  short: { duration: number } | null;
  short_error: string | null;
}

export default function AssembleStep({ project, refresh }: StepProps) {
  const pid = project.id;
  const [preview, setPreview] = useState<Preview | null>(null);
  const [outputs, setOutputs] = useState<Outputs | null>(null);
  const [result, setResult] = useState<AssembleResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { run, job, busy } = useJob({ project: pid, kind: "assemble", done: (j) => afterAssemble(j), failed: (m) => setError(m) });

  const load = async () => {
    setOutputs(await api.get<Outputs>(`/api/projects/${pid}/outputs`));
    try {
      setPreview(await api.get<Preview>(`/api/projects/${pid}/shots/preview`));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    load();
  }, [pid]);

  const afterAssemble = async (j: Job) => {
    setResult(j.result as AssembleResult);
    await load();
    refresh();
  };

  const assemble = async () => {
    setError(null);
    try {
      await afterAssemble(await run(() => api.post(`/api/projects/${pid}/assemble`)));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const video = outputs?.files["video.mp4"];
  const short = outputs?.files["short.mp4"];
  return (
    <div>
      <div className="panel">
        <h2>Assemble the video</h2>
        <p className="muted small">
          Each picture appears just before its first word and stays until the next beat. Shots under 0.5 s merge with a
          neighbour. Shots of 3 s or longer slowly zoom in. Output: the MP4, an FCPXML timeline for DaVinci Resolve
          (File → Import → Timeline), SRT captions, and the vertical Short (short.mp4): the opening, ending on the best
          cliffhanger, with your channel name under the pictures.
        </p>
        {preview && (
          <div className="stats">
            <div>
              <strong>{preview.stats.shots}</strong> shots
            </div>
            <div>
              <strong>{preview.stats.avg_s}s</strong> avg ({preview.stats.min_s}-{preview.stats.max_s}s)
            </div>
            <div>
              <strong>{fmtTime(preview.stats.total_s)}</strong> total
            </div>
          </div>
        )}
        {preview && preview.missing_images.length > 0 && (
          <div className="warning">
            {preview.missing_images.length} beats have no image yet (beats {preview.missing_images.slice(0, 12).join(", ")}
            {preview.missing_images.length > 12 ? "…" : ""}). They will show a red "missing image" card in the preview MP4
            and a gap in the Resolve timeline.
          </div>
        )}
        {preview && preview.unused_images.length > 0 && (
          <div className="muted small">
            {preview.unused_images.length} images are unused because their beat was too short and merged with a neighbour.
          </div>
        )}
        <div className="row">
          <button onClick={assemble} disabled={busy || !preview}>
            {busy ? "Rendering…" : video ? "Render again" : "Render the video and the Short"}
          </button>
          {outputs && (
            <button className="secondary" onClick={() => api.post(`/api/projects/${pid}/open-folder?sub=output`)}>
              Open output folder
            </button>
          )}
        </div>
        <JobProgress job={job} />
        <ErrorBox error={error} onClose={() => setError(null)} />
        {result && (
          <div className={result.drift_s < 0.1 ? "ok" : "warning"}>
            Rendered {fmtTime(result.duration)}. Picture/audio length difference: {result.drift_s.toFixed(3)} s.
            {result.short && ` Short: ${fmtTime(result.short.duration)}.`}
          </div>
        )}
        {result?.short_error && (
          <div className="warning small">
            <span>
              {result.short_error} {result.short_error.includes("Settings") && <a href="#/settings">Open Settings</a>}
            </span>
          </div>
        )}
      </div>
      {video && (
        <div className="panel">
          <div className="short-layout">
            <video controls src={`${video.url}&t=${video.modified}`} className="preview-video" />
            {short && (
              <div className="phone">
                <video controls src={`${short.url}&t=${short.modified}`} />
              </div>
            )}
          </div>
          <ul className="files">
            {Object.entries(outputs!.files).map(([name, f]) => (
              <li key={name}>
                <a href={f.url} download={name}>
                  {name}
                </a>{" "}
                <span className="muted small">
                  {(f.size / 1024 / 1024).toFixed(1)} MB · {f.path}
                </span>
              </li>
            ))}
          </ul>
          <p className="muted small">
            In DaVinci Resolve: File → Import → Timeline… → choose timeline.fcpxml. Every shot is a separate clip on V1
            and the voice-over is on A1.
          </p>
        </div>
      )}
    </div>
  );
}
