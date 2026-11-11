import { useEffect, useState } from "react";
import { api } from "../api";
import { StepProps } from "../App";
import { ErrorBox, JobProgress, useJob } from "../components";

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
export default function SiteStep({ project, refresh }: StepProps) {
  const pid = project.id;
  const [view, setView] = useState<SiteView | null>(null);
  const [form, setForm] = useState({ youtube_url: "", title: "", summary: "" });
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const { run, job, busy } = useJob({ project: pid, kind: "site_publish", done: () => load().then(refresh), failed: setError });

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
      refresh();
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
      refresh();
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
        <h2>Publish to Video Site</h2>
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
        <small className="muted">Starts as the suggested title from the publishing pack. Change it if you like.</small>
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
