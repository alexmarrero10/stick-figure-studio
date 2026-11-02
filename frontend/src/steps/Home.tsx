import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox } from "../components";
import { FORMAT_LABELS, Project } from "../types";

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

  const load = () => api.get<Project[]>("/api/projects").then(setProjects).catch((e) => setError(e.message));
  useEffect(() => {
    load();
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
          + New video
        </a>
      </div>
      <ErrorBox error={error} onClose={() => setError(null)} />
      {projects && active.length === 0 && (
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

      {archived.length > 0 && (
        <section className="archived">
          <button className="link archived-toggle" onClick={() => setShowArchived(!showArchived)}>
            {showArchived ? "▾" : "▸"} Archived ({archived.length})
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
        <Chip on={p.status.voice && !p.status.voice_stale} label="Voice" />
        <Chip on={p.status.prompts > 0} label="Prompts" />
        <Chip on={p.status.images > 0} label={`Images ${p.status.images}/${p.status.beats || "?"}`} />
        <Chip on={p.status.shots > 0} label="Assembled" />
        <Chip on={p.status.short_posts > 0} label={p.status.short_posts ? `Short on ${p.status.short_posts} apps` : "Short"} />
      </div>
      <div className="row between">
        <small className="muted">Updated {p.updated_at}</small>
        {children}
      </div>
    </div>
  );
}

function Chip({ on, label }: { on: boolean; label: string }) {
  return <span className={`chip ${on ? "on" : ""}`}>{label}</span>;
}
