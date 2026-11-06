import { useEffect, useState } from "react";
import { api } from "../api";
import { StepProps } from "../App";
import { CopyButton, ErrorBox, JobProgress, useJob } from "../components";

interface Meta {
  titles: string[];
  description: string;
  tags: string[];
  chapters: { time: string; title: string }[];
  thumbnail_prompts: string[];
  custom_thumbnails: { request: string; prompt: string }[];
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

interface SiteView {
  youtube_url: string;
  youtube_id: string | null;
  title: string;
  summary: string;
  title_options: string[];
  published: boolean;
  published_at: string | null;
  chunks: number;
  stale: boolean;
  has_voice: boolean;
  rag_ready: boolean;
}

/** Put the finished video on the public site: its details and timed narration go to the site database. */
function SitePanel({ pid }: { pid: number }) {
  const [view, setView] = useState<SiteView | null>(null);
  const [form, setForm] = useState({ youtube_url: "", title: "", summary: "" });
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const { run, job, busy } = useJob({ project: pid, kind: "site_publish", done: () => load(), failed: setError });

  const load = async () => {
    const v = await api.get<SiteView>(`/api/projects/${pid}/site`);
    setView(v);
    setForm({ youtube_url: v.youtube_url, title: v.title, summary: v.summary });
  };
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [pid]);
  if (!view) return null;

  const publish = async () => {
    const verb = view.published ? "Update" : "Publish";
    if (!window.confirm(`${verb} this video on your site? Its title, summary and narration will be saved to your Supabase database.`)) return;
    setError(null);
    setNote(null);
    try {
      await run(() => api.post(`/api/projects/${pid}/site/publish`, form));
      await load();
      setNote(view.published ? "Updated on the site." : "Published to the site.");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const unpublish = async () => {
    if (!window.confirm("Take this video off the site?")) return;
    setError(null);
    try {
      setView(await api.del<SiteView>(`/api/projects/${pid}/site/publish`));
      setNote("Removed from the site.");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const save = async () => {
    try {
      setView(await api.put<SiteView>(`/api/projects/${pid}/site`, form));
      setNote("Saved.");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const changed =
    form.youtube_url !== view.youtube_url || form.title !== view.title || form.summary !== view.summary;

  return (
    <div className="panel">
      <div className="row between">
        <h2>Your video site</h2>
        {view.published && (
          <span className={`save-status ${view.stale ? "bad" : "good"}`}>
            {view.stale ? "Voice re-recorded since publishing: update it" : `On the site since ${view.published_at} UTC`}
          </span>
        )}
      </div>
      <p className="muted small">
        After the video is on YouTube, publish it here so it shows on your public site. Visitors can search it and ask
        the chatbot questions, answered with timestamps from the narration.
      </p>
      <ErrorBox error={error} onClose={() => setError(null)} />
      {!view.rag_ready && (
        <p className="warn small">Add the Gemini key and the Supabase database address on the Settings page first.</p>
      )}
      {!view.has_voice && <p className="warn small">Record the voice first: the site uses its word timings.</p>}
      <label>
        YouTube link
        <input
          value={form.youtube_url}
          onChange={(e) => setForm({ ...form, youtube_url: e.target.value })}
          placeholder="https://youtu.be/..."
        />
        {form.youtube_url && !view.youtube_id && !changed && <small className="bad">That doesn't look like a YouTube video link.</small>}
      </label>
      <label>
        Title on the site
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} list={`titles-${pid}`} />
        <datalist id={`titles-${pid}`}>
          {view.title_options.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
        <small className="muted">Pick one of the title ideas or type your own.</small>
      </label>
      <label>
        Short summary
        <textarea rows={3} value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
        <small className="muted">Shown under the video on the site. Starts as the first paragraph of the description.</small>
      </label>
      <div className="row">
        <button onClick={publish} disabled={busy || !view.rag_ready || !view.has_voice || !form.youtube_url.trim()}>
          {view.published ? "Update on site" : "Publish to site"}
        </button>
        <button className="secondary" onClick={save} disabled={!changed}>
          Save without publishing
        </button>
        {view.published && (
          <button className="secondary" onClick={unpublish} disabled={busy}>
            Remove from site
          </button>
        )}
        {note && <span className="save-status good">{note}</span>}
      </div>
      <JobProgress job={job} />
      {view.youtube_id && (
        <p className="muted small">
          Thumbnail comes from YouTube:{" "}
          <a href={`https://www.youtube.com/watch?v=${view.youtube_id}`} target="_blank" rel="noreferrer">
            open the video
          </a>
          {view.published && ` · ${view.chunks} timed passages on the site`}
        </p>
      )}
    </div>
  );
}

export default function PublishStep({ project, refresh }: StepProps) {
  const pid = project.id;
  const [meta, setMeta] = useState<Meta | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [idea, setIdea] = useState("");
  const [asking, setAsking] = useState(false);

  const askThumbnail = async () => {
    setAsking(true);
    setError(null);
    try {
      setMeta(await api.post<Meta>(`/api/projects/${pid}/publish/thumbnails`, { request: idea }));
      setIdea("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAsking(false);
    }
  };

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
            <p className="muted small">Suggested by Claude:</p>
            <ul className="copy-list">
              {meta.thumbnail_prompts.map((t) => (
                <li key={t}>
                  <span className="small">{t}</span> <CopyButton text={t} />
                </li>
              ))}
            </ul>
            <h4>Ask Claude</h4>
            <p className="muted small">
              Describe the thumbnail you have in mind and Claude writes the image prompt, in the video's style and with
              its characters' looks.
            </p>
            <textarea
              rows={3}
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              placeholder="e.g. Saddam peeking out of the hole with a soldier's flashlight shining right on his face"
            />
            <div className="row">
              <button onClick={askThumbnail} disabled={asking || !idea.trim()}>
                {asking ? "Writing…" : "Write the prompt"}
              </button>
            </div>
            {meta.custom_thumbnails.length > 0 && (
              <ul className="copy-list">
                {meta.custom_thumbnails.map((t, n) => (
                  <li key={n}>
                    <span className="small">
                      <span className="muted">Your idea: {t.request}</span>
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
        </>
      )}
      <SitePanel pid={pid} />
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
