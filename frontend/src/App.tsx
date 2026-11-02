import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ErrorBox } from "./components";
import { Project } from "./types";
import Home from "./steps/Home";
import Ideas from "./steps/Ideas";
import SettingsPage from "./steps/Settings";
import ScriptStep from "./steps/Script";
import BeatsStep from "./steps/Beats";
import VoiceStep from "./steps/Voice";
import ImagesStep from "./steps/Images";
import AssembleStep from "./steps/Assemble";
import PublishStep from "./steps/Publish";
import ShortStep from "./steps/Short";

export const STEPS = [
  { key: "script", label: "1. Script" },
  { key: "beats", label: "2. Beats" },
  { key: "voice", label: "3. Voice" },
  { key: "images", label: "4. Images" },
  { key: "assemble", label: "5. Assemble" },
  { key: "publish", label: "6. Publish" },
  { key: "short", label: "7. Short" },
] as const;

type Route =
  | { page: "home" }
  | { page: "ideas" }
  | { page: "settings" }
  | { page: "project"; id: number; step: string };

function parseHash(): Route {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/");
  if (parts[0] === "ideas") return { page: "ideas" };
  if (parts[0] === "settings") return { page: "settings" };
  if (parts[0] === "p" && parts[1]) {
    // Prompts and images share one step now; old #/p/1/prompts links open it.
    const step = parts[2] === "prompts" ? "images" : parts[2] || "script";
    return { page: "project", id: Number(parts[1]), step };
  }
  return { page: "home" };
}

export function go(path: string) {
  window.location.hash = path;
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash());
  useEffect(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">
          Stick Figure Studio
        </a>
        <nav>
          <a href="#/">Projects</a>
          <a href="#/ideas">New video</a>
          <a href="#/settings">Settings</a>
        </nav>
      </header>
      <main>
        {route.page === "home" && <Home />}
        {route.page === "ideas" && <Ideas />}
        {route.page === "settings" && <SettingsPage />}
        {route.page === "project" && <ProjectView id={route.id} step={route.step} />}
      </main>
    </div>
  );
}

function ProjectView({ id, step }: { id: number; step: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    api.get<Project>(`/api/projects/${id}`).then(setProject).catch((e) => setError(e.message));
  }, [id]);
  useEffect(refresh, [refresh]);

  if (error) return <ErrorBox error={error} />;
  if (!project) return <p className="muted">Loading…</p>;
  const s = project.status;
  // Yellow until every beat has its picture, green once all are in.
  const imagesWarn = s.prompts_missing > 0 || s.images < s.beats;
  const badge: Record<string, string> = {
    script: s.script ? `${s.script_words} words` : "",
    beats: s.beats ? (s.beats_stale ? "stale" : `${s.beats}`) : "",
    voice: s.voice ? (s.voice_stale ? "stale" : "done") : "",
    images: s.prompts && s.prompts_missing ? `${s.prompts_missing} prompts missing` : s.prompts || s.images ? `${s.images}/${s.beats}` : "",
    assemble: s.shots ? "done" : "",
    publish: s.publish ? "done" : "",
    short: s.short_posts ? `on ${s.short_posts} apps` : s.short ? "made" : "",
  };
  const props = { project, refresh };
  return (
    <div className="project">
      <div className="project-head">
        <h1>{project.title}</h1>
        <button className="link" onClick={() => api.post(`/api/projects/${id}/open-folder`)}>
          Open project folder
        </button>
      </div>
      <nav className="stepper">
        {STEPS.map((st) => (
          <a key={st.key} href={`#/p/${id}/${st.key}`} className={st.key === step ? "active" : ""}>
            <span>{st.label}</span>
            {badge[st.key] && (
              <small
                className={
                  badge[st.key].includes("stale") || badge[st.key].includes("missing") || (st.key === "images" && imagesWarn)
                    ? "warn"
                    : ""
                }
              >
                {badge[st.key]}
              </small>
            )}
          </a>
        ))}
      </nav>
      <section className="step">
        {step === "script" && <ScriptStep {...props} />}
        {step === "beats" && <BeatsStep {...props} />}
        {step === "voice" && <VoiceStep {...props} />}
        {step === "images" && <ImagesStep {...props} />}
        {step === "assemble" && <AssembleStep {...props} />}
        {step === "publish" && <PublishStep {...props} />}
        {step === "short" && <ShortStep {...props} />}
      </section>
    </div>
  );
}

export interface StepProps {
  project: Project;
  refresh: () => void;
}
