import { useEffect, useState } from "react";
import { api, Job } from "../api";
import { go } from "../App";
import { ErrorBox, Icon, JobProgress, useJob } from "../components";
import { FORMAT_LABELS, Idea, Project } from "../types";

// What the user typed is kept in this browser until it is turned into an idea, so clicking away
// doesn't lose it. Storage can be blocked (private window), so every access is guarded.
const DRAFT_KEY = "ideas-draft";
type Draft = { mode: "suggest" | "own"; theme: string; own: string; refine: boolean; trending: boolean };
const EMPTY: Draft = { mode: "own", theme: "", own: "", refine: true, trending: true };

function loadDraft(): Draft {
  try {
    // The page always opens on "Use my own idea"; only what was typed and ticked is restored.
    return { ...EMPTY, ...JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}"), mode: "own" };
  } catch {
    return EMPTY;
  }
}

function saveDraft(d: Draft) {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(d));
  } catch {
    /* not saved; the page still works */
  }
}

const RECENT = 6; // latest unsaved suggestions shown again when the page is reopened

export default function Ideas() {
  const [draft, setDraft] = useState<Draft>(loadDraft);
  const [mine, setMine] = useState<Idea | null>(null); // the idea just made from the user's own text
  const [suggestions, setSuggestions] = useState<Idea[]>([]);
  const [saved, setSaved] = useState<Idea[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { run, job, busy: suggesting } = useJob({
    project: 0,
    kind: "ideas",
    done: () => load(),
    failed: (m) => setError(m),
  });

  const update = (patch: Partial<Draft>) =>
    setDraft((d) => {
      const next = { ...d, ...patch };
      saveDraft(next);
      return next;
    });

  // Every idea not yet turned into a project: saved ones, and the latest suggestions.
  const load = () =>
    api
      .get<Idea[]>("/api/ideas?unused=true")
      .then((list) => {
        setSaved(list.filter((i) => i.saved));
        setSuggestions(list.filter((i) => !i.saved && i.source !== "user").slice(0, RECENT));
      })
      .catch((e) => setError((e as Error).message));
  useEffect(() => {
    load();
  }, []);

  const suggest = async () => {
    setBusy(true);
    setError(null);
    try {
      await run(() => api.post<Job>("/api/ideas/suggest", { theme: draft.theme, count: 3, trending: draft.trending }));
      await load();
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
      const idea = await api.post<Idea>("/api/ideas/own", { text: draft.own, refine: draft.refine });
      setMine(idea);
      update({ own: "" }); // it's saved as an idea now
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const use = async (idea: Idea) => {
    try {
      const p = await api.post<Project>(`/api/ideas/${idea.id}/use`);
      go(`/p/${p.id}/script`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const setSavedFlag = async (idea: Idea, on: boolean) => {
    try {
      await api.put(`/api/ideas/${idea.id}/saved`, { saved: on });
      if (mine?.id === idea.id) setMine({ ...idea, saved: on ? 1 : 0 });
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const shown = new Set(mine && draft.mode === "own" ? [mine.id] : []);
  const otherSaved = saved.filter((i) => !shown.has(i.id));
  const thinking = busy || suggesting;

  return (
    <div className="ideas">
      <div className="ideas-head">
        <h1>Find a story</h1>
        <p className="muted">Ideas you keep are saved on the Projects page until you start them.</p>
      </div>
      <div className="tabs">
        <button aria-pressed={draft.mode === "own"} className={draft.mode === "own" ? "active" : ""} onClick={() => update({ mode: "own" })}>
          Use my own idea
        </button>
        <button aria-pressed={draft.mode === "suggest"} className={draft.mode === "suggest" ? "active" : ""} onClick={() => update({ mode: "suggest" })}>
          Suggest ideas with Claude
        </button>
      </div>

      {draft.mode === "suggest" ? (
        <div className="panel">
          <label>
            Theme or category (optional)
            <input
              value={draft.theme}
              onChange={(e) => update({ theme: e.target.value })}
              placeholder="e.g. famous heists, Cold War spies, business collapses, survival stories"
            />
          </label>
          <label className="check">
            <input type="checkbox" checked={draft.trending} onChange={(e) => update({ trending: e.target.checked })} />
            Base ideas on history topics trending on YouTube and social media right now (searches the web, takes a
            few minutes)
          </label>
          <div className="row">
            <button onClick={suggest} disabled={thinking}>
              {thinking ? "Thinking…" : suggestions.length ? "Suggest 3 more" : "Suggest 3 ideas"}
            </button>
          </div>
          <JobProgress job={job} />
        </div>
      ) : (
        <div className="panel">
          <label>
            Your idea
            <textarea
              rows={4}
              value={draft.own}
              onChange={(e) => update({ own: e.target.value })}
              placeholder="e.g. The D.B. Cooper hijacking · How did Blitzkrieg work? · Top 5 Navy pilot UFO encounters"
            />
          </label>
          <label className="check">
            <input type="checkbox" checked={draft.refine} onChange={(e) => update({ refine: e.target.checked })} />
            Let Claude sharpen the title and hook
          </label>
          <div className="row">
            <button onClick={submitOwn} disabled={busy || !draft.own.trim()}>
              {busy ? (draft.refine ? "Claude is shaping your idea…" : "Saving…") : "Save my idea"}
            </button>
            <span className="muted small">Your idea is saved to the Projects page right away.</span>
          </div>
        </div>
      )}

      <ErrorBox error={error} onClose={() => setError(null)} />

      {mine && draft.mode === "own" && <IdeaFeature idea={mine} onUse={use} onSave={setSavedFlag} />}

      {draft.mode === "suggest" && suggestions.length > 0 && (
        <section className="idea-section">
          <h2>Latest suggestions</h2>
          <div className="idea-grid">
            {suggestions.map((i) => (
              <IdeaCard key={i.id} idea={i} onUse={use} onSave={setSavedFlag} />
            ))}
          </div>
        </section>
      )}

      {otherSaved.length > 0 && (
        <section className="idea-section">
          <h2>Saved ideas</h2>
          <div className="idea-grid">
            {otherSaved.map((i) => (
              <IdeaCard key={i.id} idea={i} onUse={use} onSave={setSavedFlag} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Tags({ idea }: { idea: Idea }) {
  return (
    <div className="chips">
      <span className="chip">{FORMAT_LABELS[idea.format] ?? "One story"}</span>
      {idea.source === "trending" && <span className="chip part">Trending</span>}
      {idea.category && <span className="chip">{idea.category}</span>}
      {idea.era && <span className="chip">{idea.era}</span>}
    </div>
  );
}

type CardProps = { idea: Idea; onUse: (i: Idea) => void; onSave: (i: Idea, on: boolean) => void };

/** One idea, given the whole width: the user's own idea after it is saved. */
function IdeaFeature({ idea, onUse, onSave }: CardProps) {
  return (
    <article className="idea-feature" aria-label="Your saved idea">
      <div className="idea-feature-main">
        <Tags idea={idea} />
        <h2>{idea.title}</h2>
        {idea.hook && <p className="idea-hook">{idea.hook}</p>}
        {idea.why_it_works && (
          <div className="idea-why">
            <h3>Why it works</h3>
            <p>{idea.why_it_works}</p>
          </div>
        )}
        {idea.documentation && idea.documentation !== idea.title && (
          <p className="idea-sources">
            <strong>Sources to start from:</strong> {idea.documentation}
          </p>
        )}
      </div>
      <div className="idea-feature-side">
        {idea.saved ? (
          <p className="saved-note">
            <Icon name="check" /> Saved on your Projects page
          </p>
        ) : (
          <p className="muted small">Not saved. It will be gone when you leave this page.</p>
        )}
        <button onClick={() => onUse(idea)}>Start project</button>
        <button className="secondary" onClick={() => onSave(idea, !idea.saved)}>
          {idea.saved ? "Remove from saved" : "Save for later"}
        </button>
      </div>
    </article>
  );
}

/** A suggested or saved idea in the grid. */
function IdeaCard({ idea, onUse, onSave }: CardProps) {
  return (
    <article className="idea card">
      <Tags idea={idea} />
      <h3>{idea.title}</h3>
      {idea.hook && <p className="idea-hook">{idea.hook}</p>}
      {idea.why_it_works && <p className="small">{idea.why_it_works}</p>}
      {idea.documentation && idea.documentation !== idea.title && <p className="muted small">Sources: {idea.documentation}</p>}
      <div className="row card-actions">
        <button className="small" onClick={() => onUse(idea)}>
          Start project
        </button>
        <button className="secondary small" onClick={() => onSave(idea, !idea.saved)}>
          {idea.saved ? "Remove from saved" : "Save for later"}
        </button>
      </div>
    </article>
  );
}
