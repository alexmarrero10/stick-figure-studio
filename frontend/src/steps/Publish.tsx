import { useEffect, useState } from "react";
import { api } from "../api";
import { StepProps } from "../App";
import { CopyButton, ErrorBox } from "../components";

interface Meta {
  titles: string[];
  description: string;
  tags: string[];
  chapters: { time: string; title: string }[];
  custom_thumbnails: { request: string; prompt: string; suggested?: boolean }[];
}

export default function PublishStep({ project, refresh }: StepProps) {
  const pid = project.id;
  const [meta, setMeta] = useState<Meta | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [idea, setIdea] = useState("");
  const [asking, setAsking] = useState<"idea" | "suggest" | null>(null);

  const askThumbnail = async (kind: "idea" | "suggest") => {
    setAsking(kind);
    setError(null);
    try {
      if (kind === "idea") {
        setMeta(await api.post<Meta>(`/api/projects/${pid}/publish/thumbnails`, { request: idea }));
        setIdea("");
      } else {
        setMeta(await api.post<Meta>(`/api/projects/${pid}/publish/thumbnails/suggest`));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAsking(null);
    }
  };
  const thumbs = meta?.custom_thumbnails ?? [];
  const hasPack = !!meta?.titles?.length;

  const removeThumbnail = async (n: number) => {
    try {
      setMeta(await api.del<Meta>(`/api/projects/${pid}/publish/thumbnails/${n}`));
    } catch (e) {
      setError((e as Error).message);
    }
  };

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
          Title options, a description with chapters and sources, and tags.
        </p>
        <button onClick={generate} disabled={busy}>
          {busy ? "Writing…" : hasPack ? "Regenerate" : "Generate publishing pack"}
        </button>
        <ErrorBox error={error} onClose={() => setError(null)} />
      </div>
      {hasPack && meta && (
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
        </>
      )}
      <div className="panel">
        <h3>Thumbnail: idea to prompt</h3>
        <p className="muted small">
          Describe the thumbnail you have in mind and Claude writes the image prompt, in the video's style and with its
          characters' looks. No idea yet? Give suggestion writes one for you; press it again for a different one.
        </p>
        <textarea
          rows={3}
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          placeholder="e.g. Saddam peeking out of the hole with a soldier's flashlight shining right on his face"
        />
        <div className="row">
          <button onClick={() => askThumbnail("idea")} disabled={!!asking || !idea.trim()}>
            {asking === "idea" ? "Writing…" : "Write the prompt"}
          </button>
          <button className="secondary" onClick={() => askThumbnail("suggest")} disabled={!!asking}>
            {asking === "suggest" ? "Thinking…" : "Give suggestion"}
          </button>
        </div>
        {thumbs.length > 0 && (
          <ul className="copy-list">
            {thumbs.map((t, n) => (
              <li key={n}>
                <span className="small">
                  <span className="muted">
                    {t.suggested ? "Claude's suggestion" : "Your idea"}: {t.request}
                  </span>
                  <br />
                  {t.prompt}
                </span>{" "}
                <CopyButton text={t.prompt} />
                <button className="link danger small" onClick={() => removeThumbnail(n)}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="muted small">Add the title text to the thumbnail yourself, since image models garble lettering.</p>
      </div>
    </div>
  );
}
