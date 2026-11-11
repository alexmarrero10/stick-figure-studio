import { useEffect, useState } from "react";
import { api } from "../api";
import { go } from "../App";
import { ErrorBox, Icon } from "../components";
import { FORMAT_LABELS, Idea, Project } from "../types";

interface Health {
  ffmpeg: boolean;
  claude_provider: "claude_code" | "api";
  claude_code: { installed: boolean; logged_in: boolean; error: string | null } | null;
  anthropic_key: boolean;
  elevenlabs_key: boolean;
  voice: { voice_id: string; name: string } | null;
  voice_error: string | null;
}

export default function Home() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [ideas, setIdeas] = useState<Idea[]>([]); // saved ideas not yet started

  const load = () => api.get<Project[]>("/api/projects").then(setProjects).catch((e) => setError(e.message));
  const loadIdeas = () =>
    api
      .get<Idea[]>("/api/ideas?saved=true&unused=true")
      .then(setIdeas)
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    loadIdeas();
    api.get<Health>("/api/settings/health").then(setHealth).catch(() => {});
  }, []);

  const archive = async (p: Project, archived: boolean) => {
    setError(null);
    try {
      await api.patch(`/api/projects/${p.id}`, { archived });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (p: Project) => {
    if (
      !window.confirm(
        `Permanently delete "${p.title}"?\n\nThis removes the project and its folder (script, voice-over, images and ` +
          `videos). It cannot be undone.`,
      )
    )
      return;
    setError(null);
    try {
      await api.del(`/api/projects/${p.id}?delete_files=true`);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const startIdea = async (idea: Idea) => {
    setError(null);
    try {
      const p = await api.post<Project>(`/api/ideas/${idea.id}/use`);
      go(`/p/${p.id}/script`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const unsaveIdea = async (idea: Idea) => {
    setError(null);
    try {
      await api.put(`/api/ideas/${idea.id}/saved`, { saved: false });
      loadIdeas();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const problems: string[] = [];
  if (health) {
    if (!health.ffmpeg) problems.push("FFmpeg was not found on PATH. Install it with: winget install Gyan.FFmpeg");
    if (health.claude_provider === "api" && !health.anthropic_key) problems.push("Anthropic API key is missing.");
    if (health.claude_provider === "claude_code" && health.claude_code?.error) problems.push(health.claude_code.error);
    if (!health.elevenlabs_key) problems.push("ElevenLabs API key is missing.");
    if (health.voice_error) problems.push(health.voice_error);
  }

  const active = projects?.filter((p) => !p.archived) ?? [];
  const archived = projects?.filter((p) => p.archived) ?? [];

  return (
    <div className="home">
      {problems.length > 0 && (
        <div className="warning">
          <strong>Setup needed</strong>
          <ul>
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
          <a href="#/settings">Open Settings</a>
        </div>
      )}
      <div className="row between">
        <h1>Your videos</h1>
        <a className="button" href="#/ideas">
          <Icon name="plus" /> New project
        </a>
      </div>
      <ErrorBox error={error} onClose={() => setError(null)} />
      {projects && active.length === 0 && ideas.length === 0 && (
        <div className="empty">
          <p>
            {archived.length
              ? "No active videos. Archived ones are below."
              : "No videos yet. Start with an idea: get suggestions from Claude or bring your own."}
          </p>
          <a className="button" href="#/ideas">
            Find an idea
          </a>
        </div>
      )}
      <div className="cards">
        {active.map((p) => (
          <ProjectCard key={p.id} p={p}>
            <button className="link" onClick={() => archive(p, true)}>
              Archive
            </button>
          </ProjectCard>
        ))}
      </div>

      {ideas.length > 0 && (
        <section className="saved-ideas" aria-labelledby="saved-ideas-title">
          <div className="row between">
            <h2 id="saved-ideas-title">Saved ideas</h2>
            <a href="#/ideas">Find more ideas</a>
          </div>
          <ul className="saved-idea-list">
            {ideas.map((i) => (
              <li key={i.id} className="saved-idea">
                <div className="saved-idea-text">
                  <h3>{i.title}</h3>
                  {i.hook && <p className="muted">{i.hook}</p>}
                  <small className="muted">
                    {FORMAT_LABELS[i.format] ?? "One story"}
                    {i.created_at ? `, saved ${i.created_at.slice(0, 10)}` : ""}
                  </small>
                </div>
                <div className="saved-idea-actions">
                  <button onClick={() => startIdea(i)}>Start project</button>
                  <button className="link" onClick={() => unsaveIdea(i)}>
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {archived.length > 0 && (
        <section className="archived">
          <button className="link archived-toggle" onClick={() => setShowArchived(!showArchived)}>
            <span className={showArchived ? "turn open" : "turn"}><Icon name="chevron" /></span> Archived ({archived.length})
          </button>
          {showArchived && (
            <div className="cards">
              {archived.map((p) => (
                <ProjectCard key={p.id} p={p}>
                  <span className="row">
                    <button className="link" onClick={() => archive(p, false)}>
                      Restore
                    </button>
                    <button className="link danger" onClick={() => remove(p)}>
                      Delete
                    </button>
                  </span>
                </ProjectCard>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function ProjectCard({ p, children }: { p: Project; children: React.ReactNode }) {
  return (
    <div className={`card ${p.archived ? "is-archived" : ""}`}>
      <a href={`#/p/${p.id}/script`}>
        <h3>{p.title}</h3>
      </a>
      <div className="chips">
        {p.format && p.format !== "story" && <span className="chip">{FORMAT_LABELS[p.format]}</span>}
        <Chip on={p.status.script} label={p.status.script ? `${p.status.script_words} words` : "No script"} />
        <Chip on={p.status.beats > 0 && !p.status.beats_stale} label="Beats" />
        <Chip on={p.status.voice && !p.status.voice_stale} label="Voice" />
        <Chip
          on={p.status.images_complete}
          part={!p.status.images_complete}
          label={`Images ${p.status.images_filled}/${p.status.beats || "?"}`}
        />
        <Chip on={p.status.shots > 0} label="Assembled" />
        <Chip on={p.status.publish} label="Publish pack" />
        <Chip on={p.status.site} label="On your site" />
      </div>
      <div className="row between">
        <small className="muted">Updated {p.updated_at}</small>
        {children}
      </div>
    </div>
  );
}

// on = done (green), part = blank or partly done (yellow), neither = grey.
function Chip({ on, part, label }: { on: boolean; part?: boolean; label: string }) {
  return <span className={`chip ${on ? "on" : part ? "part" : ""}`}>{label}</span>;
}
