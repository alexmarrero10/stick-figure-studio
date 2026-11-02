import { useEffect, useState } from "react";
import { api } from "../api";
import { StepProps } from "../App";
import { CopyButton, ErrorBox } from "../components";

interface Meta {
  titles: string[];
  description: string;
  tags: string[];
  chapters: { time: string; title: string }[];
  thumbnail_prompts: string[];
}

const CHECKLIST = [
  "Facts checked against the research brief, with sources listed in the description",
  "Edited in DaVinci Resolve: music, sound effects, a few custom touches (adds originality)",
  "ElevenLabs paid plan active (needed for commercial use of the voice)",
  "No copyrighted music, footage, logos or real photos used",
  "Captions file (captions.srt) uploaded to YouTube",
  "Video is at least 8:00 so mid-roll ads are available",
  "Altered or synthetic content disclosure only needed if anything realistic was added",
];

export default function PublishStep({ project, refresh }: StepProps) {
  const pid = project.id;
  const [meta, setMeta] = useState<Meta | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Meta | null>(`/api/projects/${pid}/publish`).then(setMeta).catch(() => {});
  }, [pid]);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      setMeta(await api.post<Meta>(`/api/projects/${pid}/publish`));
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="panel">
        <h2>Publishing pack</h2>
        <p className="muted small">
          Title options, a description with chapters and sources, tags, and thumbnail prompts in the same style.
        </p>
        <button onClick={generate} disabled={busy}>
          {busy ? "Writing…" : meta ? "Regenerate" : "Generate publishing pack"}
        </button>
        <ErrorBox error={error} onClose={() => setError(null)} />
      </div>
      {meta && (
        <>
          <div className="panel">
            <h3>Titles</h3>
            <ul className="copy-list">
              {meta.titles.map((t) => (
                <li key={t}>
                  <span>{t}</span> <CopyButton text={t} />
                </li>
              ))}
            </ul>
          </div>
          <div className="panel">
            <div className="row between">
              <h3>Description</h3>
              <CopyButton text={meta.description} />
            </div>
            <pre className="description">{meta.description}</pre>
          </div>
          <div className="panel">
            <div className="row between">
              <h3>Tags</h3>
              <CopyButton text={meta.tags.join(", ")} />
            </div>
            <p>{meta.tags.join(", ")}</p>
          </div>
          <div className="panel">
            <h3>Thumbnail prompts</h3>
            <ul className="copy-list">
              {meta.thumbnail_prompts.map((t) => (
                <li key={t}>
                  <span className="small">{t}</span> <CopyButton text={t} />
                </li>
              ))}
            </ul>
            <p className="muted small">Add the title text to the thumbnail yourself, since image models garble lettering.</p>
          </div>
        </>
      )}
      <div className="panel">
        <h3>Before you upload</h3>
        <ul className="checklist">
          {CHECKLIST.map((c) => (
            <li key={c}>
              <label className="check">
                <input type="checkbox" /> {c}
              </label>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
