"""Helpers shared by tests in more than one file."""
import array
import hashlib
import math
import os
import time
import wave
from pathlib import Path

from PIL import Image


def make_png(path: Path, created: str | None = None, mtime: float | None = None):
    im = Image.new("RGB", (160, 90), "white")
    if created:
        from PIL.PngImagePlugin import PngInfo
        info = PngInfo()
        info.add_text("Creation Time", created)
        im.save(path, pnginfo=info)
    else:
        im.save(path)
    if mtime:
        os.utime(path, (mtime, mtime))


def project_with_beats(db, n_beats: int) -> int:
    p = db.create_project("Franklin test")
    words = " ".join(f"w{i}." for i in range(n_beats))
    v = db.save_script(p["id"], words, "generated")
    db.replace_beats(p["id"], v["id"], [{"idx": i, "word_start": i, "word_end": i, "text": f"w{i}."}
                                        for i in range(n_beats)])
    return p["id"]


class FakeClaude:
    """Returns a style guide with a recurring ship, and one scene per requested beat. Records requests."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def json(self, system, messages, schema, max_tokens=32000, effort=None):
        sys_text = system if isinstance(system, str) else system[0]["text"]
        ask = messages[-1]["content"]
        self.calls.append((sys_text, ask))
        if "props" in schema["properties"]:
            return {"palette": "navy blue, mustard gold", "setting_notes": "Arctic, 1840s.",
                    "characters": [{"name": "Franklin", "look": "stick figure with a plaid tartan scarf"}],
                    "props": [{"name": "Erebus", "look": "a three-masted ship with a black hull and one gold stripe"}],
                    "locations": [{"name": "Tundra", "look": "flat white snowy tundra under a pale gray sky"}]}
        if "beats" in schema["properties"]:  # the cast step: Franklin is in every image
            section = ask.split("BEATS TO CAST:")[1]
            idxs = [int(line.split(":")[0]) for line in section.strip().splitlines() if line.strip()]
            return {"beats": [{"idx": i, "cast": [{"name": "franklin", "variant": ""}]} for i in idxs]}
        section = ask.split("BEATS TO ILLUSTRATE:")[1].split("Narration just after")[0]
        idxs = [int(line.split(":")[0]) for line in section.strip().splitlines() if line.strip() and line[0] != " "]
        return {"scenes": [{"idx": i, "label": f"Scene {i}",
                            "scene": f"Beat {i}: a three-masted ship with a black hull and one gold stripe."} for i in idxs]}


def fake_embed(texts, task):
    """Deterministic bag-of-words vectors: texts sharing words point the same way."""
    out = []
    for t in texts:
        v = [0.0] * 512
        for w in t.lower().split():
            w = w.strip(".,:;!?()[]\"'")
            if len(w) > 2:
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 512] += 1.0
        out.append(v)
    return out


def doc(url, title, text):
    return {"url": url, "title": title, "source_type": "web", "text": text, "status": "ok", "words": 999}


ROOT = Path(__file__).resolve().parents[2]


def make_wav(path, seconds, rate=44100, tone_spans=()):
    n = int(seconds * rate)
    a = array.array("h", [0] * n)
    for s, e in tone_spans:
        for i in range(int(s * rate), int(e * rate)):
            a[i] = int(8000 * math.sin(i / 10))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(a.tobytes())


def wait_job(job, expect=None, timeout=20):
    """Waits for a background job (its dict or id) to finish and returns it; with expect, checks its status."""
    from app import jobs
    job_id = job["id"] if isinstance(job, dict) else job
    end = time.time() + timeout
    while jobs.get(job_id)["status"] in ("running", "stopping") and time.time() < end:
        time.sleep(0.02)
    j = jobs.get(job_id)
    if expect:
        assert j["status"] == expect, j
    return j
