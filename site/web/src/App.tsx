import { FormEvent, useEffect, useRef, useState } from "react";
import { fmtTime, getJSON, SearchHit, Video } from "./api";
import { Chat } from "./Chat";
import { Player, PlayerHandle } from "./Player";

/* Routes (in the URL hash, so any static host works):  #/   #/?q=search   #/watch/12?t=95 */
interface Route {
  page: "home" | "watch";
  q: string;
  id: number;
  t: number;
}

function parse(): Route {
  const [path, query = ""] = window.location.hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(query);
  const m = path.match(/^\/watch\/(\d+)/);
  return {
    page: m ? "watch" : "home",
    q: params.get("q") || "",
    id: m ? Number(m[1]) : 0,
    t: Number(params.get("t") || 0),
  };
}

function go(hash: string) {
  window.location.hash = hash;
}

function useRoute(): Route {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

function SearchBar({ initial }: { initial: string }) {
  const [q, setQ] = useState(initial);
  useEffect(() => setQ(initial), [initial]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    go(q.trim() ? `/?q=${encodeURIComponent(q.trim())}` : "/");
  };
  return (
    <form className="search" role="search" onSubmit={submit}>
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search every story: a person, a place, a question…"
        aria-label="Search the videos"
        maxLength={200}
      />
      <button type="submit">Search</button>
    </form>
  );
}

function Card({ v }: { v: SearchHit }) {
  const link = `#/watch/${v.id}${v.moment ? `?t=${Math.floor(v.moment.start_s)}` : ""}`;
  return (
    <article className="card">
      <a href={link} className="thumb">
        <img src={v.thumbnail_url} alt="" loading="lazy" />
        <span className="duration">{fmtTime(v.duration_s)}</span>
      </a>
      <div className="card-body">
        <h3>
          <a href={`#/watch/${v.id}`}>{v.title}</a>
        </h3>
        {v.moment ? (
          <a className="moment" href={link}>
            <span className="ts">▶ {fmtTime(v.moment.start_s)}</span> “{clip(v.moment.text, 180)}”
          </a>
        ) : (
          <p className="summary">{v.summary}</p>
        )}
      </div>
    </article>
  );
}

function clip(text: string, n: number): string {
  return text.length <= n ? text : text.slice(0, n).replace(/\s+\S*$/, "") + "…";
}

function Home({ q }: { q: string }) {
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setHits(null);
    setError(null);
    const url = q ? `/api/search?q=${encodeURIComponent(q)}` : "/api/videos";
    getJSON<SearchHit[]>(url)
      .then((r) => setHits(r.map((v) => ({ ...v, moment: v.moment ?? null }))))
      .catch((e) => setError(e.message));
  }, [q]);

  return (
    <main className="home">
      {!q && (
        <section className="hero">
          <h1>True history, told simply.</h1>
          <p>Narrated stick-figure stories about real events. Search every video by meaning, then ask questions about it.</p>
        </section>
      )}
      {q && <h2 className="results-title">Results for “{q}”</h2>}
      {error && <p className="error">{error}</p>}
      {!hits && !error && <p className="muted">Loading…</p>}
      {hits && hits.length === 0 && (
        <p className="muted">{q ? "No video talks about that yet. Try other words." : "No videos yet. Check back soon."}</p>
      )}
      <div className="grid">{hits?.map((v) => <Card key={v.id} v={v} />)}</div>
    </main>
  );
}

function Watch({ id, t }: { id: number; t: number }) {
  const [video, setVideo] = useState<Video | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const [more, setMore] = useState(false);
  const player = useRef<PlayerHandle>(null);

  useEffect(() => {
    setVideo(null);
    getJSON<Video>(`/api/videos/${id}`)
      .then((v) => {
        setVideo(v);
        document.title = `${v.title} | NextDoorHistorian`;
      })
      .catch((e) => setError(e.message));
    return () => {
      document.title = "NextDoorHistorian";
    };
  }, [id]);

  // A new ?t= on the same video (e.g. a search result) seeks instead of reloading the player.
  useEffect(() => {
    if (video) player.current?.seek(t);
  }, [t]);

  if (error) return <main className="watch"><p className="error">{error}</p></main>;
  if (!video) return <main className="watch"><p className="muted">Loading…</p></main>;

  return (
    <main className={`watch ${chatOpen ? "with-chat" : ""}`}>
      <div className="watch-main">
        <Player ref={player} videoId={video.youtube_id} start={t} />
        <div className="watch-info">
          <div className="title-row">
            <h1>{video.title}</h1>
            {!chatOpen && (
              <button className="open-chat" onClick={() => setChatOpen(true)}>
                Ask about this video
              </button>
            )}
          </div>
          <p className="muted small">
            {video.published_at && `Published ${video.published_at} · `}
            {fmtTime(video.duration_s)} ·{" "}
            <a href={`https://www.youtube.com/watch?v=${video.youtube_id}`} target="_blank" rel="noreferrer">
              Watch on YouTube
            </a>
          </p>
          <p className="summary">{video.summary}</p>
          {video.description && (
            <>
              <button className="link" onClick={() => setMore(!more)}>
                {more ? "Show less" : "Show the full description and sources"}
              </button>
              {more && <pre className="description">{video.description}</pre>}
            </>
          )}
        </div>
      </div>
      {chatOpen && (
        <Chat
          videoId={video.id}
          seek={(s) => player.current?.seek(s)}
          time={() => player.current?.time() ?? null}
          onClose={() => setChatOpen(false)}
        />
      )}
    </main>
  );
}

export default function App() {
  const route = useRoute();
  return (
    <>
      <header className="top">
        <a href="#/" className="brand" aria-label="NextDoorHistorian home">
          <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
            <circle cx="16" cy="8" r="5" fill="none" stroke="currentColor" strokeWidth="2.5" />
            <path d="M16 13v10M16 23l-6 7M16 23l6 7M8 17h16" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
          </svg>
          <span>NextDoorHistorian</span>
        </a>
        <SearchBar initial={route.page === "home" ? route.q : ""} />
      </header>
      {route.page === "watch" ? <Watch id={route.id} t={route.t} /> : <Home q={route.q} />}
      <footer className="foot">Stories by NextDoorHistorian. Every video is researched from cited sources.</footer>
    </>
  );
}
