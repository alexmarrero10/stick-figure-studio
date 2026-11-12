import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { StepProps } from "../App";
import { CopyButton, ErrorBox, JobProgress, useJob, Icon } from "../components";

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
  characters: { name: string; variant: string }[] | null;
  things: { objects: { name: string; view: string }[]; place: string } | null;
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
  main_characters: { title: string; name: string; variant: string; images: number }[];
  character_sheet: string;
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
type BulkResp = {
  images: ImagesResp;
  warnings: string[];
  added: Record<string, number>;
  skipped: number;
  unplaced: string[];
};

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
  const [drag, setDrag] = useState<string | null>(null); // path of the image being dragged
  const [over, setOver] = useState<number | null>(null); // slot it's hovering over
  const [uploading, setUploading] = useState(false);
  const pickRef = useRef<HTMLInputElement>(null);
  const [pickSlot, setPickSlot] = useState<number | null>(null); // empty slot the file picker fills
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
    if (!only_missing && data?.prompts.length && !window.confirm("Rewrite every prompt? Prompts you edited by hand are rewritten too.")) return;
    setError(null);
    try {
      await run(() => api.post(`/api/projects/${pid}/prompts/generate`, { only_missing, new_style }));
      await afterPrompts();
    } catch (e) {
      fail(e);
    }
  };

  const checkLooks = async () => {
    setError(null);
    setNote(null);
    try {
      const j = await run(() => api.post(`/api/projects/${pid}/prompts/check-looks`));
      const r = j.result as { fixed: number; skipped_edited: number; batches: number[] };
      setNote(
        (r.fixed
          ? `Fixed ${r.fixed} prompts that left out a look. Remake batch${r.batches.length > 1 ? "es" : ""} ${r.batches.join(", ")} in Flow to use them.`
          : "Every prompt already has the looks of its characters, objects and place.") +
          (r.skipped_edited ? ` ${r.skipped_edited} prompts you edited by hand were left alone.` : ""),
      );
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

  // One zip with every batch's download inside (or several zips): each image goes to its own batch.
  const uploadAll = async (files: FileList | File[]) => {
    const list = Array.from(files).filter((f) => /\.(png|jpe?g|webp|zip)$/i.test(f.name));
    if (!list.length) return;
    setUploading(true);
    setError(null);
    setNote(null);
    const fd = new FormData();
    list.forEach((f) => fd.append("files", f));
    fd.append("last_modified", JSON.stringify(list.map((f) => f.lastModified)));
    try {
      const r = await api.post<BulkResp>(`/api/projects/${pid}/images/upload-all`, fd);
      setBatches(r.images.batches);
      setWarnings(r.warnings || []);
      const parts = Object.entries(r.added).map(([b, n]) => `batch ${b}: ${n}`);
      const total = Object.values(r.added).reduce((a, n) => a + n, 0);
      setNote(
        `Added ${total} image${total === 1 ? "" : "s"}${parts.length ? ` (${parts.join(", ")})` : ""}.` +
          (r.skipped ? ` Skipped ${r.skipped} whose slot or file name is already filled.` : "") +
          (r.unplaced.length
            ? ` Couldn't tell which batch ${r.unplaced.length} belong in, so they weren't added: ` +
              `${r.unplaced.slice(0, 5).join(", ")}${r.unplaced.length > 5 ? "…" : ""}. Add those to their batch below.`
            : ""),
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

  // Drop an image on a slot: an image already there swaps places with it.
  const move = async (path: string, to: number) => {
    if (batch?.slots[to]?.image?.path === path) return;
    try {
      const r = await api.post<ImagesResp>(`/api/projects/${pid}/images/${active}/move`, { path, to });
      setBatches(r.batches);
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  // Put one picked (or dropped) file into an empty slot.
  const uploadToSlot = async (slot: number, file: File) => {
    if (!/\.(png|jpe?g|webp)$/i.test(file.name)) {
      setError("Pick a PNG, JPG or WebP image.");
      return;
    }
    setError(null);
    setNote(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.post<{ images: ImagesResp; warnings: string[] }>(
        `/api/projects/${pid}/images/${active}/slot/${slot}`,
        fd,
      );
      setBatches(r.images.batches);
      setWarnings(r.warnings || []);
      setNote(`Added ${file.name} to slot ${slot + 1}.`);
      refresh();
    } catch (e) {
      fail(e);
    }
  };

  const pickFor = (slot: number) => {
    setPickSlot(slot);
    pickRef.current?.click();
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
          the .zip) on the batch below. Each prompt starts with a short title that is different for every image in the
          batch (e.g. "Victorian London street"). Flow names the image after it, so every image lands next to its prompt. Re-uploading a batch only
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
          {data.style && data.prompts.length > 0 && (
            <button
              className="secondary"
              onClick={checkLooks}
              disabled={busy}
              title="Finds the recurring objects and place in each image and fixes prompts that leave out their look"
            >
              Check objects + places
            </button>
          )}
          <button className="secondary" onClick={rescan}>
            Rescan folders
          </button>
          {totalImages > 0 && (
            <a className="button" href={`#/p/${pid}/voice`}>
              Next: voice <Icon name="next" />
            </a>
          )}
        </div>
        {data.prompts.length > 0 && (
          <div
            className={`dropzone ${uploading ? "busy" : ""}`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (e.dataTransfer.files.length) uploadAll(e.dataTransfer.files);
            }}
          >
            <div className="dropzone-row">
              <label className="button secondary small">
                {uploading ? "Uploading…" : "Bulk upload: all batches at once"}
                <input
                  type="file"
                  multiple
                  accept="image/*,.zip,application/zip"
                  hidden
                  onChange={(e) => {
                    if (e.target.files) uploadAll(e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>
              <span className="muted small">
                One .zip with every batch's Flow download inside (zips or folders), or several zips at once. Each image
                goes to its batch by its title.
              </span>
            </div>
          </div>
        )}
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

      {data.character_sheet && (
        <div className="panel">
          <h3 className="small">First: make the main characters in Flow (before batch 1)</h3>
          <p className="small muted">
            These characters appear in many pictures, so Flow makes one reference image of each first and then
            reuses it in every batch. Characters seen only a few times just use their description.
          </p>
          <ul className="small">
            {data.main_characters.map((c) => (
              <li key={c.title}>
                <strong>{c.title}</strong> <span className="muted">({c.images} pictures)</span>
              </li>
            ))}
          </ul>
          <div className="dropzone-row">
            <CopyButton text={data.character_sheet} label="Copy the character sheet for Flow" />
            <a className="button secondary small" href={`/api/projects/${pid}/prompts/characters`} target="_blank" rel="noreferrer">
              characters.txt
            </a>
          </div>
        </div>
      )}

      {(data.prompts.length > 0 || batches.length > 0) && (
        <div className="panel">
          <div className="tabs">
            {Array.from({ length: nBatches }, (_, i) => i + 1).map((n) => {
              const b = batches.find((x) => x.batch_no === n);
              return (
                <button key={n} className={`${n === active ? "active" : ""} ${complete(b) ? "done" : ""}`} onClick={() => setActive(n)}>
                  Batch {n} {complete(b) && <span className="good"><Icon name="check" size={14} /></span>}{" "}
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

          <input
            ref={pickRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f && pickSlot !== null) uploadToSlot(pickSlot, f);
              e.target.value = "";
              setPickSlot(null);
            }}
          />
          <p className="muted small">Drag a picture onto another slot to swap them. Click an empty slot to add one.</p>
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
                        {r.characters && (
                          <div className="muted small">
                            In this image:{" "}
                            {r.characters.length
                              ? r.characters.map((c) => c.name + (c.variant ? ` (${c.variant})` : "")).join(", ")
                              : "no main characters"}
                          </div>
                        )}
                        {r.things && (r.things.objects.length > 0 || r.things.place) && (
                          <div className="muted small">
                            {r.things.objects.length > 0 &&
                              "Objects: " + r.things.objects.map((o) => o.name + (o.view ? ` (${o.view})` : "")).join(", ")}
                            {r.things.objects.length > 0 && r.things.place && " · "}
                            {r.things.place && `Place: ${r.things.place}`}
                          </div>
                        )}
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
                    className={`slot ${slot.image ? "" : "empty"} ${over === k ? "drop-target" : ""} ${
                      drag && drag === slot.image?.path ? "dragging" : ""
                    }`}
                    draggable={!!slot.image}
                    title={slot.image ? "Drag onto another slot to swap" : "Click to pick an image for this slot"}
                    onClick={() => !slot.image && batch && pickFor(k)}
                    onDragStart={(e) => {
                      if (!slot.image) return;
                      e.dataTransfer.effectAllowed = "move";
                      setDrag(slot.image.path);
                    }}
                    onDragEnd={() => {
                      setDrag(null);
                      setOver(null);
                    }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      if (over !== k) setOver(k);
                    }}
                    onDragLeave={() => setOver((o) => (o === k ? null : o))}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setOver(null);
                      const file = e.dataTransfer.files[0];
                      if (file && !slot.image && batch) uploadToSlot(k, file);
                      else if (drag) move(drag, k);
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
                      <div className="placeholder">No image · click to add</div>
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
                {batch.extra.map((img) => (
                  <div
                    key={img.path}
                    className={`slot extra ${drag === img.path ? "dragging" : ""}`}
                    draggable
                    onDragStart={() => setDrag(img.path)}
                    onDragEnd={() => {
                      setDrag(null);
                      setOver(null);
                    }}
                  >
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
