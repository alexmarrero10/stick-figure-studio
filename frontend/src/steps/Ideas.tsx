import { useEffect, useState } from "react";
import { api, Job } from "../api";
import { go } from "../App";
import { ErrorBox, JobProgress, useJob } from "../components";
import { FORMAT_LABELS, Idea, Project } from "../types";

export default function Ideas() {
  const [mode, setMode] = useState<"suggest" | "own">("suggest");
  const [theme, setTheme] = useState("");
  const [own, setOwn] = useState("");
  const [refine, setRefine] = useState(true);
  const [trending, setTrending] = useState(true);
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [saved, setSaved] = useState<Idea[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { run, job, busy: suggesting } = useJob({
    project: 0,
    kind: "ideas",
    done: (j) => setIdeas((prev) => [...(j.result as Idea[]), ...prev]),
    failed: (m) => setError(m),
  });

  const loadSaved = () => api.get<Idea[]>("/api/ideas?saved=true").then(setSaved).catch(() => {});
  useEffect(() => {
    loadSaved();
  }, []);

  const suggest = async () => {
    setBusy(true);
    setError(null);
    try {
      const done = await run(() => api.post<Job>("/api/ideas/suggest", { theme, count: 10, trending }));
      setIdeas((prev) => [...(done.result as Idea[]), ...prev]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitOwn = async () => {
    setBusy(true);
    setError(null);
    try {
      const idea = await api.post<Idea>("/api/ideas/own", { text: own, refine });
      setIdeas((prev) => [idea, ...prev]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const use = async (idea: Idea) => {
    const p = await api.post<Project>(`/api/ideas/${idea.id}/use`);
    go(`/p/${p.id}/script`);
  };

  const toggleSave = async (idea: Idea) => {
    await api.put(`/api/ideas/${idea.id}/saved`, { saved: !idea.saved });
    setIdeas((list) => list.map((i) => (i.id === idea.id ? { ...i, saved: idea.saved ? 0 : 1 } : i)));
    loadSaved();
  };

  return (
    <div className="ideas">
      <h1>Find a story</h1>
      <div className="tabs">
        <button className={mode === "suggest" ? "active" : ""} onClick={() => setMode("suggest")}>
          Suggest ideas with Claude
        </button>
        <button className={mode === "own" ? "active" : ""} onClick={() => setMode("own")}>
          Use my own idea
        </button>
      </div>

      {mode === "suggest" ? (
        <div className="panel">
          <label>
            Theme or category (optional)
            <input
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              placeholder="e.g. famous heists, Cold War spies, business collapses, survival stories"
            />
          </label>
          <label className="check">
            <input type="checkbox" checked={trending} onChange={(e) => setTrending(e.target.checked)} />
            Base ideas on history topics trending on YouTube and social media right now (searches the web, takes a
            few minutes)
          </label>
          <button onClick={suggest} disabled={busy || suggesting}>
            {busy || suggesting ? "Thinking…" : ideas.length ? "Suggest more" : "Suggest 10 ideas"}
          </button>
          <JobProgress job={job} />
        </div>
      ) : (
        <div className="panel">
          <label>
            Your idea
            <textarea
              rows={4}
              value={own}
              onChange={(e) => setOwn(e.target.value)}
              placeholder="e.g. The D.B. Cooper hijacking · How did Blitzkrieg work? · Top 5 Navy pilot UFO encounters"
            />
          </label>
          <label className="check">
            <input type="checkbox" checked={refine} onChange={(e) => setRefine(e.target.checked)} />
            Let Claude sharpen the title and hook
          </label>
          <button onClick={submitOwn} disabled={busy || !own.trim()}>
            {busy ? "Working…" : "Continue"}
          </button>
        </div>
      )}

      <ErrorBox error={error} onClose={() => setError(null)} />

      <div className="idea-list">
        {ideas.map((i) => (
          <IdeaCard key={i.id} idea={i} onUse={use} onSave={toggleSave} />
        ))}
      </div>

      {saved.length > 0 && (
        <>
          <h2>Saved ideas</h2>
          <div className="idea-list">
            {saved.map((i) => (
              <IdeaCard key={i.id} idea={i} onUse={use} onSave={toggleSave} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function IdeaCard({ idea, onUse, onSave }: { idea: Idea; onUse: (i: Idea) => void; onSave: (i: Idea) => void }) {
  return (
    <div className="idea card">
      <div className="row between">
        <h3>{idea.title}</h3>
        <div className="chips">
          {idea.source === "trending" && <span className="chip on">trending</span>}
          {idea.format && idea.format !== "story" && <span className="chip">{FORMAT_LABELS[idea.format]}</span>}
          {idea.category && <span className="chip">{idea.category}</span>}
          {idea.era && <span className="chip">{idea.era}</span>}
        </div>
      </div>
      {idea.hook && <p className="hook">"{idea.hook}"</p>}
      {idea.why_it_works && <p>{idea.why_it_works}</p>}
      {idea.documentation && <p className="muted small">Sources: {idea.documentation}</p>}
      <div className="row">
        <button onClick={() => onUse(idea)}>{idea.project_id ? "Open project" : "Use this idea"}</button>
        <button className="secondary" onClick={() => onSave(idea)}>
          {idea.saved ? "Unsave" : "Save for later"}
        </button>
      </div>
    </div>
  );
}
