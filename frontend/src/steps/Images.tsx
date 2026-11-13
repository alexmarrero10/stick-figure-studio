import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { StepProps } from "../App";
import { CopyButton, ErrorBox, JobProgress, useJob, Icon } from "../components";

// Prompts and images on one page, in three tabs that follow the work in order: prompts and style,
// the characters (and the character sheet for Flow), then the batches with each prompt beside its image.

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
    characters: { name: string; look?: string; variants?: { when: string; look: string }[] }[];
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
type Tab = "prompts" | "characters" | "batches";
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
  const [tab, setTab] = useState<Tab | null>(null); // null: open the first tab that still needs doing
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
  const expectedImages = batches.reduce((a, b) => a + b.expected, 0) || data.prompts.length;
  const characters = data.style?.characters ?? [];
  const hasPrompts = data.prompts.length > 0;

  // The tabs follow the work in order. Until one is picked, open the first one that still needs doing.
  const firstTodo: Tab = !hasPrompts ? "prompts" : totalImages > 0 || !data.character_sheet ? "batches" : "characters";
  const current = tab ?? firstTodo;
  const TABS: { key: Tab; label: string; status: string; done: boolean }[] = [
    {
      key: "prompts",
      label: "Prompts and style",
      status: hasPrompts ? `${data.prompts.length} of ${data.beats} prompts` : "Not written yet",
      done: hasPrompts && missing <= 0,
    },
    {
      key: "characters",
      label: "Characters",
      status: data.character_sheet
        ? `${data.main_characters.length} on the character sheet`
        : characters.length
          ? `${characters.length} characters, no sheet needed`
          : "Not set yet",
      done: hasPrompts && characters.length > 0,
    },
    {
      key: "batches",
      label: "Batches and images",
      status: `${totalImages} of ${expectedImages} images`,
      done: expectedImages > 0 && totalImages >= expectedImages,
    },
  ];
  const go = (t: Tab) => {
    setTab(t);
    document.getElementById(`imgtab-${t}`)?.focus();
  };
  const onTabKey = (e: KeyboardEvent) => {
    const keys = TABS.map((t) => t.key);
    const k = keys.indexOf(current);
    if (e.key === "ArrowRight") go(keys[(k + 1) % keys.length]);
    else if (e.key === "ArrowLeft") go(keys[(k + keys.length - 1) % keys.length]);
    else return;
    e.preventDefault();
  };

  return (
    <div>
      <div className="panel">
        <div className="row between">
          <h2>Image prompts and images</h2>
          {totalImages > 0 && (
            <a className="button" href={`#/p/${pid}/voice`}>
              Next: voice <Icon name="next" />
            </a>
          )}
        </div>
        <p className="muted small">
          Work through the tabs in order: write the prompts, make the main characters in Flow, then send each batch to
          Flow and add its images here.
        </p>
        {!data.beats && <div className="warning">Build the beats first.</div>}
        <JobProgress job={job} />
        <ErrorBox error={error} onClose={() => setError(null)} />
        {note && <div className="ok small">{note}</div>}
      </div>

      <div className="image-tabs" role="tablist" aria-label="Image steps">
        {TABS.map((t, i) => (
          <button
            key={t.key}
            id={`imgtab-${t.key}`}
            role="tab"
            aria-selected={current === t.key}
            aria-controls="imgpanel"
            tabIndex={current === t.key ? 0 : -1}
            className={`image-tab ${current === t.key ? "active" : ""} ${t.done ? "done" : ""}`}
            onClick={() => setTab(t.key)}
            onKeyDown={onTabKey}
          >
            <span className="dot" aria-hidden="true">
              {t.done ? <Icon name="check" size={14} /> : i + 1}
            </span>
            <span className="label">
              <span>{t.label}</span>
              <small>{t.status}</small>
            </span>
          </button>
        ))}
      </div>

      <div
        id="imgpanel"
        role="tabpanel"
        aria-labelledby={`imgtab-${current}`}
        className={`panel image-panel ${current === "prompts" ? "first-active" : ""}`}
      >
        {current === "prompts" && (
          <>
            <div className="tab-intro">
              <h3>Prompts and style</h3>
              <p className="muted small">
                One prompt per beat, {data.batch_size} per batch. Each prompt starts with a short title that is
                different for every image in its batch (e.g. "Victorian London street"). Flow names the image after it,
                so every image lands next to its prompt.
              </p>
            </div>
            <div className="row">
              <button className={hasPrompts ? "" : "primary"} onClick={() => generate(false)} disabled={busy || !data.beats}>
                {hasPrompts ? "Regenerate all prompts" : "Generate prompts"}
              </button>
              {missing > 0 && hasPrompts && (
                <button className="secondary" onClick={() => generate(true)} disabled={busy}>
                  Fill {missing} missing
                </button>
              )}
              {data.style && (
                <button className="secondary" onClick={() => generate(false, true)} disabled={busy}>
                  New style + prompts
                </button>
              )}
              {data.style && hasPrompts && (
                <button
                  className="secondary"
                  onClick={checkLooks}
                  disabled={busy}
                  title="Finds the recurring objects and place in each image and fixes prompts that leave out their look"
                >
                  Check objects + places
                </button>
              )}
            </div>
            {data.style && !data.style.props?.length && !data.style.locations?.length && hasPrompts && (
              <div className="warning small">
                These prompts were made before recurring objects and places were tracked, so things like a ship may look
                different from image to image. Click "New style + prompts" to rewrite them with a consistent look.
              </div>
            )}
            {data.style ? (
              <div className="bible">
                <section>
                  <h3 className="small">The video's style</h3>
                  <p className="style-text small">{data.style.style_prefix}</p>
                  {data.style.setting_notes && <p className="small muted">{data.style.setting_notes}</p>}
                </section>
                <div className="bible-cols">
                  <section>
                    <h3 className="small">Recurring objects</h3>
                    <p className="muted small">Described with the same words in every prompt.</p>
                    {data.style.props?.length ? (
                      <ul className="look-list small">
                        {data.style.props.map((x) => (
                          <li key={x.name}>
                            <strong>{x.name}</strong> {x.look}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="small muted">None.</p>
                    )}
                  </section>
                  <section>
                    <h3 className="small">Recurring places</h3>
                    <p className="muted small">Each one looks the same wherever it appears.</p>
                    {data.style.locations?.length ? (
                      <ul className="look-list small">
                        {data.style.locations.map((x) => (
                          <li key={x.name}>
                            <strong>{x.name}</strong> {x.look}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="small muted">None.</p>
                    )}
                  </section>
                </div>
              </div>
            ) : (
              <p className="muted small">Generating prompts also sets the video's style, characters, objects and places.</p>
            )}
            {hasPrompts && (
              <div className="tab-foot">
                <button className="secondary" onClick={() => go("characters")}>
                  Next: characters <Icon name="next" />
                </button>
              </div>
            )}
          </>
        )}

        {current === "characters" && (
          <>
            <div className="tab-intro">
              <h3>Characters</h3>
              <p className="muted small">
                Every character is described with the same words in every prompt, so they look the same from image to
                image.
              </p>
            </div>
            {data.character_sheet ? (
              <div className="sheet">
                <div className="sheet-text">
                  <h3>Make the main characters in Flow first, before batch 1</h3>
                  <p className="muted small">
                    These characters are in many pictures, so Flow makes one reference image of each and reuses it in
                    every batch. Characters seen only a few times just use their description.
                  </p>
                <ol className="sheet-list">
                  {data.main_characters.map((c) => (
                    <li key={c.title}>
                      <strong>{c.title}</strong>
                      <span className="muted small">{c.images} pictures</span>
                    </li>
                  ))}
                </ol>
                </div>
                <div className="sheet-copy">
                  <CopyButton text={data.character_sheet} label="Copy the character sheet for Flow" className="secondary big" />
                  <span className="muted small">
                    Paste it into your Flow agent, or open{" "}
                    <a href={`/api/projects/${pid}/prompts/characters`} target="_blank" rel="noreferrer">
                      characters.txt
                    </a>
                  </span>
                </div>
              </div>
            ) : (
              hasPrompts && (
                <p className="muted small">
                  No character is in enough pictures to need a reference image, so there is no character sheet. Go
                  straight to the batches.
                </p>
              )
            )}
            {characters.length > 0 ? (
              <section>
                <h3 className="small">Every character</h3>
                <ul className="look-list small">
                  {characters.map((c) => (
                    <li key={c.name}>
                      <strong>{c.name}</strong> {c.look}
                      {c.variants?.map((v) => (
                        <div key={v.when} className="muted">
                          {v.when}: {v.look}
                        </div>
                      ))}
                    </li>
                  ))}
                </ul>
              </section>
            ) : (
              <div className="row">
                <span className="muted small">The characters are set when the prompts are written.</span>
                <button className="secondary small" onClick={() => go("prompts")}>
                  Go to prompts
                </button>
              </div>
            )}
            {hasPrompts && (
              <div className="tab-foot">
                <button className="secondary" onClick={() => go("batches")}>
                  Next: batches <Icon name="next" />
                </button>
              </div>
            )}
          </>
        )}

        {current === "batches" && !hasPrompts && !batches.length && (
          <div className="row">
            <span className="muted small">Write the prompts first. Each batch of {data.batch_size} goes to Flow in one go.</span>
            <button className="secondary small" onClick={() => go("prompts")}>
              Go to prompts
            </button>
          </div>
        )}

        {current === "batches" && (hasPrompts || batches.length > 0) && (
          <>
            {hasPrompts && (
              <div
                className={`dropzone bulk ${uploading ? "busy" : ""}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (e.dataTransfer.files.length) uploadAll(e.dataTransfer.files);
                }}
              >
                <div>
                  <h3 className="small">Add every batch at once</h3>
                  <p className="muted small">
                    One .zip with every batch's Flow download inside (zips or folders), or several zips. Each image goes
                    to its batch by its title. Drop them anywhere in this box.
                  </p>
                </div>
                <div className="dropzone-row">
                  <label className="button small">
                    {uploading ? "Uploading…" : "Bulk upload all batches"}
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
                  <button className="secondary small" onClick={rescan} title="Picks up images you put in the batch folders yourself">
                    Rescan folders
                  </button>
                </div>
              </div>
            )}

            <div className="batch-bar">
              <h3 className="small">Or one batch at a time</h3>
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
            </div>

            <div className="batch-actions">
              {batchText && (
                <div className="flow-section">
                  <h3 className="small">1. Send batch {active} to Flow</h3>
                  <p className="muted small">Paste it into your Flow agent.</p>
                  {active === 1 && data.character_sheet && (
                    <p className="small">
                      Made the main characters first?{" "}
                      <button className="link small" onClick={() => go("characters")}>
                        Character sheet
                      </button>
                    </p>
                  )}
                  <div className="dropzone-row">
                    <CopyButton text={batchText} label={`Copy batch ${active} for Flow`} />
                    <a
                      className="button secondary small"
                      href={`/api/projects/${pid}/prompts/batch/${active}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      batch_{String(active).padStart(2, "0")}.txt
                    </a>
                  </div>
                </div>
              )}
              <div
                className={`dropzone ${uploading ? "busy" : ""}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
                }}
              >
                <div>
                  <h3 className="small">{batchText ? "2. " : ""}Add batch {active} images</h3>
                  <p className="muted small">Drop images or a .zip anywhere in this box. Re-uploading only adds the ones still missing.</p>
                </div>
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
                  <button className="secondary small danger" onClick={clearBatch} disabled={!batch?.count}>
                    Remove all images
                  </button>
                </div>
              </div>
            </div>
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
          </>
        )}
      </div>
    </div>
  );
}
