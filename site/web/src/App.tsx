import { FormEvent, SyntheticEvent, useEffect, useRef, useState } from "react";
import { fmtTime, getJSON, SearchHit, Video } from "./api";
import { Chat } from "./Chat";
import { Player, PlayerHandle } from "./Player";

const SITE_NAME = "Stick Figure Viewer";

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
    const on = () => {
      setRoute(parse());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

/** Some summaries were stored with literal "\n" in them; show them as real line breaks. */
function paras(text: string): string[] {
  return text
    .replace(/\\n/g, "\n")
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
}

function clip(text: string, n: number): string {
  return text.length <= n ? text : text.slice(0, n).replace(/\s+\S*$/, "") + "…";
}

/* YouTube's hqdefault.jpg is 4:3 with black bars; the 16:9 versions fill the frame. */
function thumbSrc(v: Video): string {
  return /i\.ytimg\.com\/vi\/[^/]+\/hqdefault\.jpg/.test(v.thumbnail_url)
    ? `https://i.ytimg.com/vi/${v.youtube_id}/maxresdefault.jpg`
    : v.thumbnail_url;
}
function thumbFallback(v: Video) {
  return (e: SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    const next = img.src.includes("maxresdefault") ? `https://i.ytimg.com/vi/${v.youtube_id}/mqdefault.jpg` : v.thumbnail_url;
    if (img.src !== next) img.src = next;
  };
}
/* maxresdefault can be a 120x90 grey placeholder instead of a 404 when the video has no HD thumbnail. */
function checkSize(v: Video) {
  return (e: SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    if (img.naturalWidth <= 120 && img.src.includes("maxresdefault")) img.src = `https://i.ytimg.com/vi/${v.youtube_id}/mqdefault.jpg`;
  };
}

function Thumb({ v, href, eager }: { v: Video; href: string; eager?: boolean }) {
  return (
    <a href={href} className="thumb" tabIndex={-1} aria-hidden="true">
      <img src={thumbSrc(v)} alt="" loading={eager ? "eager" : "lazy"} onError={thumbFallback(v)} onLoad={checkSize(v)} />
      <span className="duration">{fmtTime(v.duration_s)}</span>
    </a>
  );
}

function SearchBar({ initial, big }: { initial: string; big?: boolean }) {
  const [q, setQ] = useState(initial);
  useEffect(() => setQ(initial), [initial]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    go(q.trim() ? `/?q=${encodeURIComponent(q.trim())}` : "/");
  };
  return (
    <form className={`search ${big ? "big" : ""}`} role="search" onSubmit={submit}>
      <svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="M15.5 15.5 21 21" />
      </svg>
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={big ? "Search a name, place or event" : "Search the stories"}
        aria-label="Search the videos"
        maxLength={200}
      />
      <button type="submit">Search</button>
    </form>
  );
}

/** The channel's stick figure, pointing at the search box. It draws itself once when the page opens. */
function Figure() {
  return (
    <svg className="figure" viewBox="0 0 220 280" aria-hidden="true">
      <g className="ink">
        <circle cx="140" cy="56" r="30" />
        <path d="M140 86 V176" />
        <path d="M140 176 L108 262" />
        <path d="M140 176 L170 262" />
        <path d="M140 112 L46 176" />
        <path d="M140 112 L172 140 L160 166" />
      </g>
      <g className="face">
        <circle cx="129" cy="54" r="3" />
        <circle cx="151" cy="54" r="3" />
        <path d="M123 41 q5 -4 10 -2 M147 39 q5 -2 10 2 M130 67 q10 8 20 0" />
      </g>
    </svg>
  );
}

function Ring() {
  return (
    <svg className="ring" viewBox="0 0 400 100" preserveAspectRatio="none" aria-hidden="true">
      <path
        pathLength={1}
        d="M44 14 C130 0 300 -2 378 18 C406 28 404 78 360 89 C258 106 108 103 32 88 C2 80 0 30 42 15 C78 4 120 2 168 5"
      />
    </svg>
  );
}

function Hero() {
  return (
    <section className="hero">
      <div className="hero-text">
        <h1>True stories from history, drawn in stick figures.</h1>
        <p>
          Watch a story, search every video for the moment you remember, and ask questions. Every answer links to the
          second in the video it comes from.
        </p>
        <div className="ringed">
          <SearchBar initial="" big />
          <Ring />
        </div>
      </div>
      <Figure />
    </section>
  );
}

function Feature({ v }: { v: SearchHit }) {
  const link = `#/watch/${v.id}`;
  return (
    <article className="feature">
      <Thumb v={v} href={link} eager />
      <div className="feature-body">
        <p className="kicker">Newest story{v.published_at ? `, ${niceDate(v.published_at)}` : ""}</p>
        <h2>
          <a href={link}>{v.title}</a>
        </h2>
        <p className="summary">{clip(paras(v.summary)[0] ?? "", 260)}</p>
        <a className="btn" href={link}>
          Watch the story
        </a>
      </div>
    </article>
  );
}

function Card({ v }: { v: SearchHit }) {
  const link = `#/watch/${v.id}`;
  return (
    <article className="card">
      <Thumb v={v} href={link} />
      <h3>
        <a href={link}>{v.title}</a>
      </h3>
      <p className="summary">{paras(v.summary)[0]}</p>
    </article>
  );
}

function Result({ v }: { v: SearchHit }) {
  const at = v.moment ? `?t=${Math.floor(v.moment.start_s)}` : "";
  const link = `#/watch/${v.id}${at}`;
  return (
    <article className="result">
      <Thumb v={v} href={link} />
      <div>
        <h3>
          <a href={`#/watch/${v.id}`}>{v.title}</a>
        </h3>
        {v.moment ? (
          <a className="moment" href={link}>
            <span className="ts">{fmtTime(v.moment.start_s)}</span>
            <span className="quote">“{clip(v.moment.text, 220)}”</span>
          </a>
        ) : (
          <p className="summary">{paras(v.summary)[0]}</p>
        )}
      </div>
    </article>
  );
}

function niceDate(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
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

  if (q) {
    return (
      <main tabIndex={-1} className="page results">
        <h1 className="results-title">
          {hits ? `${hits.length} ${hits.length === 1 ? "story mentions" : "stories mention"}` : "Searching for"} “{q}”
        </h1>
        {error && <p className="error">{error}</p>}
        {!hits && !error && <p className="muted">Searching…</p>}
        {hits && hits.length === 0 && (
          <p className="empty">
            No video covers that yet. Try different words, or <a href="#/">browse every story</a>.
          </p>
        )}
        <div className="result-list">{hits?.map((v) => <Result key={v.id} v={v} />)}</div>
      </main>
    );
  }

  const [first, ...rest] = hits ?? [];
  return (
    <main tabIndex={-1} className="page home">
      <Hero />
      {error && <p className="error">{error}</p>}
      {!hits && !error && <p className="muted">Loading the stories…</p>}
      {hits && hits.length === 0 && <p className="empty">The first story is on its way. Check back soon.</p>}
      {first && <Feature v={first} />}
      {rest.length > 0 && (
        <section className="more">
          <h2>More stories</h2>
          <div className="grid">
            {rest.map((v) => (
              <Card key={v.id} v={v} />
            ))}
          </div>
        </section>
      )}
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
        document.title = `${v.title} | ${SITE_NAME}`;
      })
      .catch((e) => setError(e.message));
    return () => {
      document.title = SITE_NAME;
    };
  }, [id]);

  // A new ?t= on the same video (e.g. a search result) seeks instead of reloading the player.
  useEffect(() => {
    if (video) player.current?.seek(t);
  }, [t]);

  if (error)
    return (
      <main tabIndex={-1} className="page watch">
        <p className="error">{error}</p>
        <a href="#/">Back to every story</a>
      </main>
    );
  if (!video)
    return (
      <main tabIndex={-1} className="page watch">
        <div className="player skeleton" />
      </main>
    );

  return (
    <main tabIndex={-1} className={`page watch ${chatOpen ? "with-chat" : ""}`}>
      <div className="watch-main">
        <Player ref={player} videoId={video.youtube_id} start={t} />
        <div className="watch-info">
          <h1>{video.title}</h1>
          <div className="meta-row">
            <span className="muted">
              {fmtTime(video.duration_s)}
              {video.published_at && <>, published {niceDate(video.published_at)}</>}
            </span>
            <span className="actions">
              {!chatOpen && (
                <button onClick={() => setChatOpen(true)}>Ask about this video</button>
              )}
              <a className="btn ghost" href={`https://www.youtube.com/watch?v=${video.youtube_id}`} target="_blank" rel="noreferrer">
                Watch on YouTube
              </a>
            </span>
          </div>
          <div className="summary-block">
            {paras(video.summary).map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
          {video.description && (
            <>
              <button className="link" onClick={() => setMore(!more)} aria-expanded={more}>
                {more ? "Hide the description and sources" : "Show the description and sources"}
              </button>
              {more && <div className="description">{video.description.replace(/\\n/g, "\n")}</div>}
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
  const bareHome = route.page === "home" && !route.q;
  return (
    <>
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.querySelector("main")?.focus(); }}>
        Skip to content
      </a>
      <header className="top">
        <a href="#/" className="brand">
          <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
            <circle cx="16" cy="8" r="5" fill="none" stroke="currentColor" strokeWidth="2.6" />
            <path d="M16 13v10M16 23l-6 7M16 23l6 7M8 17h16" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
          </svg>
          <span>{SITE_NAME}</span>
        </a>
        {!bareHome && <SearchBar initial={route.page === "home" ? route.q : ""} />}
      </header>
      {route.page === "watch" ? <Watch id={route.id} t={route.t} /> : <Home q={route.q} />}
      <footer className="foot">
        <span>{SITE_NAME}</span>
        <span className="muted">True stories, told simply.</span>
      </footer>
    </>
  );
}
