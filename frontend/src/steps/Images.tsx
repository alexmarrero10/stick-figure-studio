import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { StepProps } from "../App";
import { CopyButton, ErrorBox, JobProgress, useJob } from "../components";

// Prompts and images on one page: each batch lists its prompts with the Flow image next to each one.

interface PromptRow {
  beat_id: number;
  idx: number;
  batch_no: number;
  scene: string;
  label: string;
  title: string;
  prompt: string;
  beat_text: string;
  edited: number;
}

interface Look {
  name: string;
  look: string;
}

interface PromptsResp {
  style: {
    style_prefix: string;
    characters: { name: string; look?: string; marker?: string; variants?: { when: string; look: string }[] }[];
    props: Look[];
    locations: Look[];
    setting_notes: string;
  } | null;
  prompts: PromptRow[];
  beats: number;
  batch_size: number;
  done_batches: number[];
  batch_texts: Record<string, string>;
}

interface Img {
  path: string;
  name: string;
  url: string;
  sort_source: string;
  position: number;
}

interface Batch {
  batch_no: number;
  expected: number;
  count: number;
  folder: string;
  slots: { beat_idx: number; beat_text: string; image: Img | null }[];
  extra: Img[];
}

type ImagesResp = { batches: Batch[] };
type UploadResp = { images: ImagesResp; warnings: string[]; added: number; skipped: number };

export default function ImagesStep({ project, refresh }: StepProps) {
  const pid = project.id;
  const [data, setData] = useState<PromptsResp | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [active, setActive] = useState(1);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [labelDraft, setLabelDraft] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { run, job, busy } = useJob({
    project: pid,
    kind: "prompts",
    done: () => afterPrompts(),
    failed: (m) => setError(m),
  });

  const loadPrompts = () => api.get<PromptsResp>(`/api/projects/${pid}/prompts`).then(setData);
  const loadImages = () => api.get<ImagesResp>(`/api/projects/${pid}/images`).then((r) => setBatches(r.batches));
  useEffect(() => {
    Promise.all([loadPrompts(), loadImages()]).catch((e) => setError(e.message));
  }, [pid]);

  const fail = (e: unknown) => setError((e as Error).message);

  // --- prompts --------------------------------------------------------------

  const afterPrompts = async () => {
    await Promise.all([loadPrompts(), loadImages()]);
    refresh();
  };

  const generate = async (only_missing: boolean, new_style = false) => {
    if (!only_missing && data?.prompts.length && !window.confirm("Rewrite every prompt? Your edits and batch checkmarks are cleared.")) return;
    setError(null);
    try {
      await run(() => api.post(`/api/projects/${pid}/prompts/generate`, { only_missing, new_style }));
      await afterPrompts();
    } catch (e) {
      fail(e);
    }
  };

  // Prompts written before image titles existed get theirs automatically, once per visit.
  const untitled = data ? data.prompts.filter((p) => !p.label).length : 0;
  const titling = useRef(false);
  useEffect(() => {
    if (!untitled || busy || titling.current) return;
    titling.current = true;
    run(() => api.post(`/api/projects/${pid}/prompts/labels`))
      .then(() => loadPrompts())
      .catch((e) => setError(`Could not add image titles: ${(e as Error).message}`));
  }, [untitled, busy, pid]);

  const saveEdit = async (row: PromptRow) => {
    try {
      await api.put(`/api/projects/${pid}/prompts/${row.beat_id}`, { scene: draft, label: labelDraft });
      setEditing(null);
      loadPrompts();
    } catch (e) {
      fail(e);
    }
  };

  const regen = async (row: PromptRow) => {
    const direction = window.prompt("Any direction for this image? (optional)");
    if (direction === null) return;
    setError(null);
    try {
      await api.post(`/api/projects/${pid}/prompts/${row.beat_id}/regenerate`, { note: direction });
      loadPrompts();
    } catch (e) {
      fail(e);
    }
  };

  // --- images ---------------------------------------------------------------

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files).filter((f) => /\.(png|jpe?g|webp|zip)$/i.test(f.name));
    if (!list.length) return;
    setUploading(true);
    setError(null);
    setNote(null);
    const fd = new FormData();
    list.forEach((f) => fd.append("files", f));
    fd.append("last_modified", JSON.stringify(list.map((f) => f.lastModified)));
    try {
      const r = await api.post<UploadResp>(`/api/projects/${pid}/images/${active}/upload`, fd);
      setBatches(r.images.batches);
      setWarnings(r.warnings || []);
      setNote(
        `Added ${r.added} image${r.added === 1 ? "" : "s"}` +
          (r.skipped ? `, skipped ${r.skipped} whose slot or file name is already filled.` : "."),
      );
      refresh();
    } catch (e) {
      fail(e);
    } finally {
      setUploading(false);
    }
  };

  const rescan = async () => {
    try {
      const r = await api.post<{ images: ImagesResp; warnings: string[] }>(`/api/projects/${pid}/images/rescan-all`);
      setBatches(r.images.batches);
      setWarnings(r.warnings || []);
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  const clearBatch = async () => {
    if (!batch?.count) return;
    if (!window.confirm(`Delete all ${batch.count} images in batch ${active}? The files are removed from the batch folder.`)) return;
    try {
      const r = await api.post<ImagesResp & { removed: number }>(`/api/projects/${pid}/images/${active}/clear`);
      setBatches(r.batches);
      setWarnings([]);
      setNote(`Removed ${r.removed} images from batch ${active}.`);
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  const batch = batches.find((b) => b.batch_no === active);
  // One entry per slot (null = empty), then the extras.
  const layout: (string | null)[] = batch
    ? [...batch.slots.map((s) => s.image?.path ?? null), ...batch.extra.map((i) => i.path)]
    : [];

  const move = async (from: number, to: number) => {
    if (!batch || from === to) return;
    const paths = [...layout];
    if (paths[to] === null) {
      // Dropped on an empty slot: just move it there.
      paths[to] = paths[from];
      paths[from] = null;
    } else {
      const [p] = paths.splice(from, 1);
      paths.splice(to, 0, p);
    }
    while (paths.length > batch.slots.length && paths[paths.length - 1] === null) paths.pop();
    try {
      const r = await api.put<ImagesResp>(`/api/projects/${pid}/images/${active}/order`, { paths });
      setBatches(r.batches);
    } catch (e) {
      fail(e);
    }
  };

  const remove = async (img: Img) => {
    try {
      const r = await api.post<ImagesResp>(`/api/projects/${pid}/images/${active}/delete`, { path: img.path });
      setBatches(r.batches);
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  if (!data) return <ErrorBox error={error} />;
  const nBatches = Math.max(1, Math.ceil(data.beats / data.batch_size), batches.length);
  const rows = data.prompts.filter((p) => p.batch_no === active);
  const byIdx = new Map(rows.map((r) => [r.idx, r]));
  const missing = data.beats - data.prompts.length;
  const batchText = data.batch_texts[String(active)] ?? "";
  const complete = (b?: Batch) => !!b && b.expected > 0 && b.count >= b.expected;
  const totalImages = batches.reduce((a, b) => a + Math.min(b.count, b.expected), 0);

  return (
    <div>
      <div className="panel">
        <h2>Image prompts and images</h2>
        <p className="muted small">
          One prompt per beat, {data.batch_size} per batch. Copy a batch into your Flow agent, then drop the images (or
          the .zip) on the batch below. Each prompt starts with its number and title (e.g. "1 - Victorian London
          street"), which Flow uses to name the image, so every image lands next to its prompt. Re-uploading a batch only
          adds the images that are still missing.
        </p>
        <div className="row">
          <button onClick={() => generate(false)} disabled={busy || !data.beats}>
            {data.prompts.length ? "Regenerate all prompts" : "Generate prompts"}
          </button>
          {missing > 0 && data.prompts.length > 0 && (
            <button className="secondary" onClick={() => generate(true)} disabled={busy}>
              Fill {missing} missing
            </button>
          )}
          {data.style && (
            <button className="secondary" onClick={() => generate(false, true)} disabled={busy}>
              New style + prompts
            </button>
          )}
          <button className="secondary" onClick={rescan}>
            Rescan folders
          </button>
          {totalImages > 0 && (
            <a className="button" href={`#/p/${pid}/assemble`}>
              Next: assemble →
            </a>
          )}
        </div>
        <JobProgress job={job} />
        <ErrorBox error={error} onClose={() => setError(null)} />
        {!data.beats && <div className="warning">Build the beats first.</div>}
        {data.style && !data.style.props?.length && !data.style.locations?.length && data.prompts.length > 0 && (
          <div className="warning small">
            These prompts were made before recurring objects and places were tracked, so things like a ship may look
            different from image to image. Click "New style + prompts" to rewrite them with a consistent look.
          </div>
        )}
      </div>

      {data.style && (
        <details className="panel">
          <summary>
            <strong>Visual bible: style, characters, recurring objects and places</strong>
          </summary>
          <p className="small">{data.style.style_prefix}</p>
          <h3 className="small">Characters (same words in every prompt)</h3>
          <ul className="small">
            {data.style.characters.map((c) => (
              <li key={c.name}>
                <strong>{c.name}</strong>: {c.look || `stick figure with ${c.marker}`}
                {c.variants?.map((v) => (
                  <div key={v.when} className="muted">
                    {v.when}: {v.look}
                  </div>
                ))}
              </li>
            ))}
          </ul>
          {data.style.props?.length > 0 && (
            <>
              <h3 className="small">Recurring objects (same words in every prompt)</h3>
              <ul className="small">
                {data.style.props.map((x) => (
                  <li key={x.name}>
                    <strong>{x.name}</strong>: {x.look}
                  </li>
                ))}
              </ul>
            </>
          )}
          {data.style.locations?.length > 0 && (
            <>
              <h3 className="small">Recurring places</h3>
              <ul className="small">
                {data.style.locations.map((x) => (
                  <li key={x.name}>
                    <strong>{x.name}</strong>: {x.look}
                  </li>
                ))}
              </ul>
            </>
          )}
          {data.style.setting_notes && <p className="small muted">{data.style.setting_notes}</p>}
        </details>
      )}

      {(data.prompts.length > 0 || batches.length > 0) && (
        <div className="panel">
          <div className="tabs">
            {Array.from({ length: nBatches }, (_, i) => i + 1).map((n) => {
              const b = batches.find((x) => x.batch_no === n);
              return (
                <button key={n} className={`${n === active ? "active" : ""} ${complete(b) ? "done" : ""}`} onClick={() => setActive(n)}>
                  Batch {n} {complete(b) && <small className="good">✓</small>}{" "}
                  {b && (
                    <small className={complete(b) ? "good" : "warn"}>
                      {b.count}/{b.expected}
                    </small>
                  )}
                </button>
              );
            })}
          </div>

          {batchText && (
            <div className="flow-section">
              <h3 className="small">Send batch {active} to Flow</h3>
              <div className="dropzone-row">
                <CopyButton text={batchText} label={`Copy batch ${active} for Flow`} />
                <span className="muted small">Paste it into your Flow agent.</span>
              </div>
              <div className="dropzone-row">
                <a
                  className="button secondary small"
                  href={`/api/projects/${pid}/prompts/batch/${active}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  batch_{String(active).padStart(2, "0")}.txt
                </a>
                <span className="muted small">The same prompts as a text file.</span>
              </div>
            </div>
          )}
          <h3 className="small">Add batch {active} images</h3>
          <div
            className={`dropzone ${uploading ? "busy" : ""}`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
            }}
          >
            <div className="dropzone-row">
              <label className="button secondary small">
                {uploading ? "Uploading…" : "Add images or a .zip"}
                <input
                  type="file"
                  multiple
                  accept="image/*,.zip,application/zip"
                  hidden
                  onChange={(e) => {
                    if (e.target.files) upload(e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>
              <button
                className="secondary small"
                onClick={() => api.post(`/api/projects/${pid}/open-folder?sub=images/batch_${String(active).padStart(2, "0")}`)}
              >
                Open batch folder
              </button>
              <button className="secondary small danger" onClick={clearBatch} disabled={!batch?.count}>
                Remove all images
              </button>
              <span className="muted small">or drag images / a .zip anywhere in this box</span>
            </div>
          </div>
          {note && <div className="ok small">{note}</div>}
          {warnings.map((w) => (
            <div key={w} className="warning small">
              {w}
            </div>
          ))}

          <ol className="pair-list">
            {(batch?.slots ?? rows.map((r) => ({ beat_idx: r.idx, beat_text: r.beat_text, image: null }))).map((slot, k) => {
              const r = byIdx.get(slot.beat_idx);
              return (
                <li key={slot.beat_idx} className="pair">
                  <div className="pair-text">
                    <div className="row between">
                      <strong>{k + 1}</strong>
                      <span className="muted small">beat {slot.beat_idx}</span>
                    </div>
                    <div className="narration">"{slot.beat_text}"</div>
                    {!r ? (
                      <div className="muted small">No prompt yet.</div>
                    ) : editing === r.beat_id ? (
                      <>
                        <label>
                          Image title
                          <input value={labelDraft} onChange={(e) => setLabelDraft(e.target.value)} placeholder="e.g. Victorian London street" />
                        </label>
                        <textarea rows={4} value={draft} onChange={(e) => setDraft(e.target.value)} />
                        <div className="row">
                          <button className="small" onClick={() => saveEdit(r)}>
                            Save
                          </button>
                          <button className="secondary small" onClick={() => setEditing(null)}>
                            Cancel
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="scene small">
                          <span className="title">{r.title}.</span> {r.scene} {r.edited ? <span className="chip">edited</span> : null}
                        </div>
                        <div className="row">
                          <CopyButton text={r.prompt} />
                          <button
                            className="secondary small"
                            onClick={() => {
                              setEditing(r.beat_id);
                              setDraft(r.scene);
                              setLabelDraft(r.label || r.title.replace(/^\d+ - /, ""));
                            }}
                          >
                            Edit
                          </button>
                          <button className="secondary small" onClick={() => regen(r)}>
                            Regenerate
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                  <div
                    className={`slot ${slot.image ? "" : "empty"}`}
                    draggable={!!slot.image}
                    onDragStart={() => setDrag(k)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      if (drag === null || e.dataTransfer.files.length) return;
                      e.preventDefault();
                      e.stopPropagation();
                      move(drag, k);
                      setDrag(null);
                    }}
                  >
                    {slot.image ? (
                      <>
                        <img src={slot.image.url} alt={slot.image.name} />
                        <div className="row between small">
                          <span className="muted" title={slot.image.name}>
                            {slot.image.sort_source === "label" ? slot.image.name : slot.image.sort_source}
                          </span>
                          <button className="link danger small" onClick={() => remove(slot.image!)}>
                            Remove
                          </button>
                        </div>
                      </>
                    ) : (
                      <div className="placeholder">No image</div>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
          {batch && batch.extra.length > 0 && (
            <>
              <div className="warning small">
                {batch.extra.length} extra image{batch.extra.length === 1 ? "" : "s"} not matched to a prompt. Drag one onto a
                slot or remove it.
              </div>
              <div className="image-grid">
                {batch.extra.map((img, j) => (
                  <div key={img.path} className="slot extra" draggable onDragStart={() => setDrag(batch.slots.length + j)}>
                    <img src={img.url} alt={img.name} />
                    <div className="row between small">
                      <span className="muted" title={img.name}>
                        {img.name}
                      </span>
                      <button className="link danger small" onClick={() => remove(img)}>
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
