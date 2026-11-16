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
    <div className="publish-layout">
      <div>
        <div className="panel">
          <h2>Publishing Pack</h2>
          <p className="muted small">
            A suggested title, a description with chapters and sources, and tags.
          </p>
          <button onClick={generate} disabled={busy}>
            {busy ? "Writing…" : hasPack ? "Regenerate" : "Generate publishing pack"}
          </button>
          <ErrorBox error={error} onClose={() => setError(null)} />
        </div>
        {hasPack && meta && (
          <>
            <div className="panel">
              <div className="row between">
                <h3>Suggested title</h3>
                <CopyButton text={meta.titles[0]} />
              </div>
              <p>{meta.titles[0]}</p>
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
      </div>
      <section className="panel panel-main publish-thumbs" aria-labelledby="thumb-heading">
        <h2 id="thumb-heading">Thumbnail: idea to prompt</h2>
        <p className="muted small">
          Describe the picture you want and Claude writes the image prompt, in the video's style and with its characters'
          looks. No idea yet? Give suggestion writes one; press it again for a different one.
        </p>
        <label className="thumb-idea">
          <span>Your idea</span>
          <textarea
            rows={7}
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && idea.trim() && !asking) askThumbnail("idea");
            }}
            placeholder="e.g. the main character frozen in shock next to the one object the story turns on"
          />
        </label>
        <div className="row thumb-actions">
          <button className="primary" onClick={() => askThumbnail("idea")} disabled={!!asking || !idea.trim()}>
            {asking === "idea" ? "Writing…" : "Write the prompt"}
          </button>
          <button className="secondary" onClick={() => askThumbnail("suggest")} disabled={!!asking}>
            {asking === "suggest" ? "Thinking…" : "Give suggestion"}
          </button>
          <span className="muted small thumb-hint">Ctrl + Enter writes it too</span>
        </div>
        {thumbs.length > 0 && (
          <ul className="thumb-list">
            {thumbs.map((t, n) => ({ t, n })).reverse().map(({ t, n }) => ( // newest first; n stays the stored index for Remove
              <li key={n}>
                <div className="thumb-from">
                  <span className="chip">{t.suggested ? "Claude's suggestion" : "Your idea"}</span>
                  <span className="muted small">{t.request}</span>
                </div>
                <p className="thumb-prompt">{t.prompt}</p>
                <div className="row">
                  <CopyButton text={t.prompt} />
                  <button className="link danger small" onClick={() => removeThumbnail(n)}>
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="muted small">Add the title text to the thumbnail yourself, since image models garble lettering.</p>
      </section>
    </div>
  );
}
