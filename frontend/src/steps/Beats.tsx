import { useEffect, useState } from "react";
import { api } from "../api";
import { StepProps } from "../App";
import { ErrorBox, Stale } from "../components";
import { Beat } from "../types";

export default function BeatsStep({ project, refresh }: StepProps) {
  const pid = project.id;
  const [beats, setBeats] = useState<Beat[]>([]);
  const [review, setReview] = useState(true);
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<Beat[]>(`/api/projects/${pid}/beats`).then(setBeats).catch((e) => setError(e.message));
  }, [pid]);

  const build = async () => {
    if (project.status.prompts && !window.confirm("Rebuilding beats deletes the image prompts for every beat. Continue?")) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ beats: Beat[]; review_applied: number; review_skipped: string[] }>(
        `/api/projects/${pid}/beats/build`,
        { review },
      );
      setBeats(res.beats);
      setInfo(review ? `Claude adjusted ${res.review_applied} beat boundaries.` : null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const op = async (o: Record<string, unknown>) => {
    setError(null);
    try {
      setBeats(await api.post<Beat[]>(`/api/projects/${pid}/beats/ops`, { ops: [o] }));
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const startEdit = (b: Beat) => {
    setEditing(b.idx);
    setDraft(b.text);
  };

  const saveEdit = async (b: Beat) => {
    if (draft.trim().split(/\s+/).join(" ") === b.text) {
      setEditing(null);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      setBeats(await api.put<Beat[]>(`/api/projects/${pid}/beats/${b.idx}/text`, { text: draft }));
      setEditing(null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const total = beats.reduce((a, b) => a + b.est_seconds, 0);
  const s = project.status;

  return (
    <div>
      <div className="panel">
        <h2>Beats</h2>
        <p className="muted small">
          The narration is cut into short chunks at natural pauses. Each beat (about 0.5-3 seconds of speech) becomes one
          picture. Click a word to split a beat there, merge a beat into the next one, or edit a beat's text. Editing a beat
          also updates the script.
        </p>
        <Stale show={s.beats_stale}>The script changed since these beats were built. Rebuild them.</Stale>
        <div className="row">
          <label className="check">
            <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} />
            Let Claude review the boundaries for better pictures
          </label>
          <button onClick={build} disabled={busy || !s.script}>
            {busy ? "Building…" : beats.length ? "Rebuild beats" : "Build beats"}
          </button>
          {beats.length > 0 && (
            <a className="button" href={`#/p/${pid}/voice`}>
              Next: voice →
            </a>
          )}
        </div>
        {info && <div className="ok">{info}</div>}
        <ErrorBox error={error} onClose={() => setError(null)} />
        {beats.length > 0 && (
          <p className="muted small">
            {beats.length} beats · avg {(total / beats.length).toFixed(1)} s · {Math.ceil(beats.length / 24)} batches of
            24 images
          </p>
        )}
      </div>
      <div className="beat-list">
        {beats.map((b, i) => {
          const words = b.text.split(/\s+/);
          const dur = b.start !== undefined && b.end !== undefined ? b.end - b.start : b.est_seconds;
          return (
            <div key={b.id} className={`beat ${dur > 5 ? "long" : dur < 1 ? "short" : ""}`}>
              <div className="beat-meta">
                <strong>#{b.idx}</strong>
                <span className="muted small">
                  words {b.word_start}-{b.word_end}
                </span>
                <span className="muted small">{b.start !== undefined ? `${dur.toFixed(1)} s` : `~${dur.toFixed(1)} s`}</span>
              </div>
              {editing === b.idx ? (
                <div className="beat-edit">
                  <textarea
                    value={draft}
                    rows={2}
                    autoFocus
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        saveEdit(b);
                      } else if (e.key === "Escape") setEditing(null);
                    }}
                  />
                  {s.voice && <span className="muted small">Saving changes the script, so the voice will need to be regenerated.</span>}
                </div>
              ) : (
              <div className="beat-text">
                {words.map((w, k) => (
                  <span
                    key={k}
                    className={k > 0 ? "word splittable" : "word"}
                    title={k > 0 ? "Split here" : undefined}
                    onClick={() => k > 0 && op({ op: "split", beat: b.idx, at: b.word_start + k })}
                  >
                    {w}{" "}
                  </span>
                ))}
              </div>
              )}
              <div className="beat-actions">
                {editing === b.idx ? (
                  <>
                    <button className="small" onClick={() => saveEdit(b)} disabled={saving}>
                      {saving ? "Saving…" : "Save"}
                    </button>
                    <button className="small secondary" onClick={() => setEditing(null)} disabled={saving}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button className="link small" onClick={() => startEdit(b)} disabled={editing !== null}>
                      Edit text
                    </button>
                    {i < beats.length - 1 && (
                      <button className="link small" onClick={() => op({ op: "merge", beat: b.idx })}>
                        Merge with next
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
