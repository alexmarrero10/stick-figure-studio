import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ErrorBox, Icon } from "./components";
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
import SiteStep from "./steps/Site";

export const STEPS = [
  { key: "script", label: "Script" },
  { key: "beats", label: "Beats" },
  { key: "voice", label: "Voice" },
  { key: "images", label: "Images" },
  { key: "assemble", label: "Assemble" },
  { key: "publish", label: "Publish" },
  { key: "site", label: "Publish to Video Site" },
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
    const step = parts[2] === "prompts" ? "images" : parts[2] === "short" ? "assemble" : parts[2] || "script";
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
      <a className="skip" href="#content" onClick={(e) => { e.preventDefault(); document.getElementById("content")?.focus(); }}>
        Skip to content
      </a>
      <header className="topbar">
        <a className="brand" href="#/">
          <Mark />
          <span>Stick Figure Studio</span>
        </a>
        <span className="version" title="App version">v{__APP_VERSION__}</span>
        <nav aria-label="Main">
          <a href="#/" aria-current={route.page === "home" || route.page === "project" ? "page" : undefined}>Projects</a>
          <a href="#/ideas" aria-current={route.page === "ideas" ? "page" : undefined}>New project</a>
          <a href="#/settings" aria-current={route.page === "settings" ? "page" : undefined}>Settings</a>
        </nav>
      </header>
      <main id="content" tabIndex={-1}>
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
  const imagesWarn = s.prompts_missing > 0 || !s.images_complete;
  const badge: Record<string, string> = {
    script: s.script ? `${s.script_words} words` : "",
    beats: s.beats ? (s.beats_stale ? "stale" : `${s.beats}`) : "",
    voice: s.voice ? (s.voice_stale ? "stale" : "done") : "",
    images: s.prompts && s.prompts_missing ? `${s.prompts_missing} prompts missing` : s.prompts || s.images ? `${s.images_filled}/${s.beats}` : "",
    assemble: s.shots ? "done" : "",
    publish: s.publish ? "done" : "",
    site: s.site ? "published" : "",
  };
  const props = { project, refresh };
  return (
    <div className="project">
      <div className="project-head">
        <h1>{project.title}</h1>
      </div>
      <nav className="stepper" aria-label="Video steps">
        <ol>
          {STEPS.map((st, i) => {
            const note = badge[st.key];
            const warn = note.includes("stale") || note.includes("missing") || (st.key === "images" && !!note && imagesWarn);
            const state = !note ? "todo" : warn ? "warn" : "done";
            return (
              <li key={st.key} className={`${state} ${st.key === step ? "active" : ""}`}>
                <a href={`#/p/${id}/${st.key}`} aria-current={st.key === step ? "step" : undefined}>
                  <span className="dot" aria-hidden="true">
                    {state === "done" ? <Icon name="check" size={14} /> : i + 1}
                  </span>
                  <span className="label">
                    <span>{st.label}</span>
                    <small>{note || "Not started"}</small>
                  </span>
                </a>
              </li>
            );
          })}
        </ol>
      </nav>
      <section className="step">
        {step === "script" && <ScriptStep {...props} />}
        {step === "beats" && <BeatsStep {...props} />}
        {step === "voice" && <VoiceStep {...props} />}
        {step === "images" && <ImagesStep {...props} />}
        {step === "assemble" && <AssembleStep {...props} />}
        {step === "publish" && <PublishStep {...props} />}
        {step === "site" && <SiteStep {...props} />}
      </section>
    </div>
  );
}

/** The channel's stick figure, small, for the top bar. */
function Mark() {
  return (
    <svg className="mark" viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
      <circle cx="16" cy="8" r="5" fill="none" stroke="currentColor" strokeWidth="2.6" />
      <path d="M16 13v10M16 23l-6 7M16 23l6 7M16 17l-8-3M16 17l9 -5" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle className="mark-ring" cx="26" cy="9" r="4.5" fill="none" strokeWidth="2" />
    </svg>
  );
}

export interface StepProps {
  project: Project;
  refresh: () => void;
}
