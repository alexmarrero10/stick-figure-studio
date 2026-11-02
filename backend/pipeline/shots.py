"""Turn beats + word timings into timed shots.

Each beat's picture appears slightly before its first word starts (cut_lead_s) and stays until
the next beat begins. Shots under min_shot_s merge with a neighbour. Pictures are never zoomed:
every shot is shown at scale 1.0, however long it lasts. All times are snapped to whole frames.
"""
from __future__ import annotations

from typing import Any

from pipeline.scenes import ends_sentence


def build_shots(beats: list[dict[str, Any]], words: list[dict[str, Any]], images: dict[int, str],
                audio_duration: float, cfg: dict[str, Any], fps: int = 30) -> dict[str, Any]:
    """beats: [{idx, word_start, word_end, text}], words: [{idx, start, end}], images: beat idx → path.

    Returns {"shots": [{image, start_frame, end_frame, scale, beat_ids}], "unused_images": [...],
             "total_frames": int}.
    """
    if not beats:
        return {"shots": [], "unused_images": [], "total_frames": 0}
    lead = cfg.get("cut_lead_s", 0.08)
    min_f = round(cfg.get("min_shot_s", 1.0) * fps)
    total_frames = round((audio_duration + cfg.get("tail_s", 0.6)) * fps)

    # 1. Raw cut points in frames, monotonic.
    starts: list[int] = []
    for i, b in enumerate(beats):
        f = 0 if i == 0 else max(0, round((words[b["word_start"]]["start"] - lead) * fps))
        if starts and f <= starts[-1]:
            f = starts[-1] + 1
        starts.append(f)
    segs = []
    for i, b in enumerate(beats):
        end = starts[i + 1] if i + 1 < len(beats) else max(total_frames, starts[i] + 1)
        last_word = b["text"].split()[-1]
        segs.append({
            "beats": [b["idx"]],
            "start": starts[i],
            "end": end,
            "image": images.get(b["idx"]),
            "own": {b["idx"]: end - starts[i]},  # frames each beat contributed, for picking the image
            "sentence_end": ends_sentence(last_word),
        })

    # 2. Merge short shots into a neighbour, preferring one in the same sentence.
    while len(segs) > 1:
        short = [k for k, s in enumerate(segs) if s["end"] - s["start"] < min_f]
        if not short:
            break
        k = min(short, key=lambda k: segs[k]["end"] - segs[k]["start"])
        cands = []
        if k > 0:
            cands.append((k - 1, not segs[k - 1]["sentence_end"]))
        if k + 1 < len(segs):
            cands.append((k + 1, not segs[k]["sentence_end"]))
        same = [c for c, same_sentence in cands if same_sentence]
        pool = same or [c for c, _ in cands]
        n = min(pool, key=lambda c: segs[c]["end"] - segs[c]["start"])
        a, b = (n, k) if n < k else (k, n)
        sa, sb = segs[a], segs[b]
        own = {**sa["own"], **sb["own"]}
        keep_beat = max(own, key=lambda bi: own[bi])
        merged = {
            "beats": sa["beats"] + sb["beats"],
            "start": sa["start"],
            "end": sb["end"],
            "image": images.get(keep_beat) or sa["image"] or sb["image"],
            "own": own,
            "sentence_end": sb["sentence_end"],
        }
        segs[a:b + 1] = [merged]

    used = {s["image"] for s in segs if s["image"]}
    unused = sorted({p for p in images.values() if p and p not in used})

    # 3. One shot per segment, no zoom.
    shots = [{"image": s["image"], "start_frame": s["start"], "end_frame": s["end"], "scale": 1.0,
              "beat_ids": s["beats"]} for s in segs]
    return {"shots": shots, "unused_images": unused, "total_frames": shots[-1]["end_frame"]}
