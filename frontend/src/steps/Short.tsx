import { useEffect, useState } from "react";
import { api, fmtTime, Job } from "../api";
import { StepProps } from "../App";
import { ErrorBox, JobProgress, useJob } from "../components";

type Platform = "youtube" | "instagram" | "facebook" | "tiktok";
const PLATFORMS: { key: Platform; label: string; where: string }[] = [
  { key: "youtube", label: "YouTube", where: "Shorts" },
  { key: "instagram", label: "Instagram", where: "Reels" },
  { key: "facebook", label: "Facebook", where: "Reels on your Page" },
  { key: "tiktok", label: "TikTok", where: "your profile" },
];

interface ShortRow {
  title: string;
  caption: string;
  hashtags: string[];
  youtube_url: string;
  rendered_at: string | null;
  duration_s: number | null;
}

interface Post {
  id: number;
  platform: Platform;
  status: "posted" | "error";
  url: string | null;
  error: string | null;
  rendered_at: string | null;
  created_at: string;
}

interface ShortResp {
  short: ShortRow;
  video: { url: string; modified: number; size: number } | null;
  posts: Post[];
  connected: Record<Platform, boolean>;
  channel_name: string;
  min_seconds: number;
  max_seconds: number;
  cut_seconds: number | null;
  opening_text: string;
  previews: Record<Platform, { title: string; text: string }>;
}

export default function ShortStep({ project, refresh }: StepProps) {
  const pid = project.id;
  const [data, setData] = useState<ShortResp | null>(null);
  const [form, setForm] = useState({ title: "", caption: "", hashtags: "", youtube_url: "" });
  const [chosen, setChosen] = useState<Record<Platform, boolean>>({ youtube: true, instagram: true, facebook: true, tiktok: true });
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const render = useJob({ project: pid, kind: "short", done: () => afterRender(), failed: (m) => setError(m) });
  const posting = useJob({ project: pid, kind: "short_publish", done: (j) => afterPublish(j), failed: (m) => setError(m) });

  const apply = (d: ShortResp) => {
    setData(d);
    setForm({
      title: d.short.title,
      caption: d.short.caption,
      hashtags: d.short.hashtags.join(" "),
      youtube_url: d.short.youtube_url,
    });
  };
  const load = () => api.get<ShortResp>(`/api/projects/${pid}/short`).then(apply).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, [pid]);

  const afterRender = async () => {
    await load();
    refresh();
  };

  const afterPublish = async (j: Job) => {
    const res = j.result as { platform: string; status: string }[];
    const ok = res.filter((r) => r.status === "posted").length;
    const bad = res.filter((r) => r.status === "error").length;
    setNote(`Posted to ${ok} app${ok === 1 ? "" : "s"}` + (bad ? `, ${bad} failed (see below).` : "."));
    await load();
    refresh();
  };

  if (!data) return <ErrorBox error={error} />;
  const s = data.short;
  const channel = data.channel_name.trim().replace(/^@+/, "");
  const dirty =
    form.title !== s.title ||
    form.caption !== s.caption ||
    form.hashtags !== s.hashtags.join(" ") ||
    form.youtube_url !== s.youtube_url;

  const fail = (e: unknown) => setError((e as Error).message);

  const saveText = async () => {
    setError(null);
    try {
      apply(
        await api.put<ShortResp>(`/api/projects/${pid}/short`, {
          ...form,
          hashtags: form.hashtags.split(/[\s,]+/).filter(Boolean),
        }),
      );
    } catch (e) {
      fail(e);
    }
  };

  const writeText = async () => {
    if ((s.title || s.caption) && !window.confirm("Replace the title, caption and hashtags with new ones?")) return;
    setWriting(true);
    setError(null);
    try {
      if (form.youtube_url !== s.youtube_url) await saveText();
      apply(await api.post<ShortResp>(`/api/projects/${pid}/short/text`));
    } catch (e) {
      fail(e);
    } finally {
      setWriting(false);
    }
  };

  const make = async () => {
    setError(null);
    setNote(null);
    try {
      await render.run(() => api.post(`/api/projects/${pid}/short/render`));
      await afterRender();
    } catch (e) {
      fail(e);
    }
  };

  const publish = async () => {
    const targets = PLATFORMS.filter((p) => chosen[p.key] && data.connected[p.key]);
    if (!targets.length) return;
    if (dirty) await saveText();
    const again = targets.filter((t) => data.posts.some((p) => p.platform === t.key && p.status === "posted" && p.rendered_at === s.rendered_at));
    let postAgain = false;
    if (again.length) {
      postAgain = window.confirm(
        `This Short is already on ${again.map((a) => a.label).join(", ")}. Post it there again?\n\n` +
          "OK posts a second copy. Cancel skips those apps.",
      );
    }
    if (!window.confirm(`Post the Short publicly to ${targets.map((t) => t.label).join(", ")} now?`)) return;
    setError(null);
    setNote(null);
    try {
      await afterPublish(
        await posting.run(() =>
          api.post(`/api/projects/${pid}/short/publish`, { platforms: targets.map((t) => t.key), again: postAgain }),
        ),
      );
    } catch (e) {
      fail(e);
    }
  };

  const latest = (pl: Platform) => data.posts.find((p) => p.platform === pl);
  const anyConnected = PLATFORMS.some((p) => data.connected[p.key]);
  const canPublish =
    !!data.video && !!s.youtube_url && !!form.title.trim() && !!form.caption.trim() && !posting.busy && !render.busy;

  return (
    <div>
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div className="short-layout">
        <div className="panel">
          <h2>Short form video</h2>
          <p className="muted small">
            The opening of the video, made vertical for phones (1080×1920). Each picture is trimmed slightly at the
            sides and fills the width, with your channel name under it on the left. It stops right after the best
            cliffhanger sentence between {data.min_seconds} and {data.max_seconds} seconds
            {data.cut_seconds ? ` (here, at ${Math.round(data.cut_seconds)} seconds)` : ""}, so viewers go to the full
            video for the rest.
          </p>
          <p>
            Channel name under the pictures:{" "}
            {channel ? <strong>@{channel}</strong> : <span className="bad">not set</span>} ·{" "}
            <a href="#/settings">{channel ? "change in Settings" : "set it in Settings"}</a>
          </p>
          <div className="row">
            <button onClick={make} disabled={render.busy || !channel || project.status.shots === 0}>
              {render.busy ? "Rendering…" : data.video ? "Make the Short again" : "Make the Short"}
            </button>
            {data.video && (
              <a className="button secondary" href={data.video.url} download="short.mp4">
                Download
              </a>
            )}
          </div>
          {project.status.shots === 0 && <div className="warning small">Assemble the video first (step 5).</div>}
          <JobProgress job={render.job} />
          {data.video && (
            <p className="muted small">
              Made {s.rendered_at} · {fmtTime(s.duration_s ?? 0)} · {(data.video.size / 1024 / 1024).toFixed(1)} MB. Make
              it again after changing images or the voice-over.
            </p>
          )}
        </div>
        <div className="phone">
          {data.video ? (
            <video controls src={`${data.video.url}&t=${data.video.modified}`} />
          ) : (
            <div className="phone-empty muted small">The Short appears here</div>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="row between">
          <h2>Title and caption</h2>
          <button className="secondary" onClick={writeText} disabled={writing || !data.opening_text}>
            {writing ? "Writing…" : s.title ? "Write new ones with Claude" : "Write with Claude"}
          </button>
        </div>
        <label>
          Link to the full video on YouTube (added to every description)
          <input
            value={form.youtube_url}
            onChange={(e) => setForm({ ...form, youtube_url: e.target.value })}
            placeholder="https://youtu.be/…"
          />
        </label>
        <label>
          Title (YouTube adds #Shorts; on the other apps it isn't shown)
          <input value={form.title} maxLength={90} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </label>
        <label>
          Caption
          <textarea rows={3} value={form.caption} onChange={(e) => setForm({ ...form, caption: e.target.value })} />
        </label>
        <label>
          Hashtags (separated by spaces, no #)
          <input value={form.hashtags} onChange={(e) => setForm({ ...form, hashtags: e.target.value })} />
        </label>
        <div className="row">
          <button onClick={saveText} disabled={!dirty}>
            Save
          </button>
          {dirty && <span className="muted small">Unsaved changes</span>}
        </div>
        {(s.title || s.caption) && (
          <details>
            <summary className="small">What each app will show</summary>
            {PLATFORMS.map((p) => (
              <div key={p.key} className="preview-text">
                <strong className="small">{p.label}</strong>
                {p.key === "youtube" && <div className="small">{data.previews[p.key].title}</div>}
                <pre className="description small">{data.previews[p.key].text}</pre>
              </div>
            ))}
            <p className="muted small">Instagram and TikTok don't make links in captions clickable; viewers can copy it.</p>
          </details>
        )}
      </div>

      <div className="panel">
        <h2>Publish</h2>
        {!anyConnected && (
          <div className="warning small">
            <span>
              No accounts are connected yet. Connect YouTube, Facebook + Instagram and TikTok on the{" "}
              <a href="#/settings">Settings page</a>.
            </span>
          </div>
        )}
        <ul className="platforms">
          {PLATFORMS.map((p) => {
            const post = latest(p.key);
            const on = data.connected[p.key];
            return (
              <li key={p.key}>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={on && chosen[p.key]}
                    disabled={!on}
                    onChange={(e) => setChosen({ ...chosen, [p.key]: e.target.checked })}
                  />
                  <span>
                    <strong>{p.label}</strong> <span className="muted small">{p.where}</span>
                  </span>
                </label>
                <span className="small">
                  {!on ? (
                    <a href="#/settings">Connect</a>
                  ) : post?.status === "posted" ? (
                    <>
                      <span className="good">Posted</span>{" "}
                      {post.url && (
                        <a href={post.url} target="_blank" rel="noreferrer">
                          View
                        </a>
                      )}
                      {post.rendered_at !== s.rendered_at && <span className="muted"> (an older version)</span>}
                    </>
                  ) : post?.status === "error" ? (
                    <span className="bad" title={post.error ?? ""}>
                      Failed: {post.error}
                    </span>
                  ) : (
                    <span className="muted">Not posted</span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
        {!s.youtube_url && data.video && <div className="warning small">Paste the full video's YouTube link above first.</div>}
        <button onClick={publish} disabled={!canPublish || !PLATFORMS.some((p) => chosen[p.key] && data.connected[p.key])}>
          {posting.busy ? "Publishing…" : "Publish short form videos"}
        </button>
        <JobProgress job={posting.job} />
        {note && <div className="ok small">{note}</div>}
      </div>
    </div>
  );
}
