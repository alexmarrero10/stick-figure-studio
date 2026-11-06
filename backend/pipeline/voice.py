"""ElevenLabs voice-over with per-word timings.

ElevenLabs' with-timestamps mode returns the start/end time of every character it speaks.
We group characters into words and map them onto the script's word indices.
"""
from __future__ import annotations

import array
import base64
import difflib
import json
import re
import time
import wave
from pathlib import Path
from typing import Any, Callable

import httpx

from pipeline import ffmpeg

API = "https://api.elevenlabs.io/v1"
DEFAULT_JOSH_ID = "ZoiZ8fuDWInAcwPXaVeq"  # "Josh - Warm, Smooth and Steady" (the old premade Josh ID now belongs to another voice)


class VoiceError(RuntimeError):
    pass


# --- voice lookup -----------------------------------------------------------

def resolve_voice(api_key: str, voice_id: str, voice_name: str = "Josh") -> dict[str, str]:
    """Confirm the configured voice exists; fall back to finding it by name."""
    headers = {"xi-api-key": api_key}
    r = httpx.get(f"{API}/voices/{voice_id}", headers=headers, timeout=30)
    if r.status_code == 200:
        v = r.json()
        return {"voice_id": v["voice_id"], "name": v.get("name", voice_name)}
    r = httpx.get(f"{API}/voices", headers=headers, timeout=30)
    if r.status_code == 401:
        raise VoiceError("ElevenLabs rejected the API key")
    r.raise_for_status()
    for v in r.json().get("voices", []):
        if v.get("name", "").lower().startswith(voice_name.lower()):
            return {"voice_id": v["voice_id"], "name": v["name"]}
    raise VoiceError(f"Voice '{voice_name}' ({voice_id}) not found in this ElevenLabs account. "
                     "Add it from the Voice Library or set a different voice_id in Settings.")


def list_voices(api_key: str) -> list[dict[str, Any]]:
    """Voices in the account (premade plus ones added from the Voice Library)."""
    r = httpx.get(f"{API}/voices", headers={"xi-api-key": api_key}, timeout=30)
    if r.status_code == 401:
        raise VoiceError("ElevenLabs rejected the API key")
    r.raise_for_status()
    voices = [
        {"voice_id": v["voice_id"], "name": v["name"], "use_case": (v.get("labels") or {}).get("use_case", ""),
         "description": v.get("description") or ""}
        for v in r.json().get("voices", [])
    ]
    return sorted(voices, key=lambda v: v["name"].lower())


# --- chunking ---------------------------------------------------------------

def chunk_text(text: str, max_chars: int = 4000) -> list[str]:
    """Split at paragraph boundaries (then sentences) into requests of at most max_chars.

    Invariant: the words of all chunks, in order, equal text.split().
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    pieces: list[str] = []
    for p in paras:
        if len(p) <= max_chars:
            pieces.append(p)
            continue
        cur = ""
        for sent in re.split(r"(?<=[.!?])\s+", p):
            if cur and len(cur) + 1 + len(sent) > max_chars:
                pieces.append(cur)
                cur = sent
            else:
                cur = f"{cur} {sent}" if cur else sent
        if cur:
            pieces.append(cur)
    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        if cur and len(cur) + 2 + len(piece) > max_chars:
            chunks.append(cur)
            cur = piece
        else:
            cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        chunks.append(cur)
    return chunks


# --- alignment → words ------------------------------------------------------

def chars_to_words(alignment: dict[str, list], offset: float = 0.0) -> list[dict[str, Any]]:
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    words: list[dict[str, Any]] = []
    cur, cur_start, cur_end = "", 0.0, 0.0
    for c, s, e in zip(chars, starts, ends):
        if c.isspace():
            if cur:
                words.append({"text": cur, "start": cur_start + offset, "end": cur_end + offset})
                cur = ""
            continue
        if not cur:
            cur_start = s
        cur += c
        cur_end = e
    if cur:
        words.append({"text": cur, "start": cur_start + offset, "end": cur_end + offset})
    return words


def _norm(w: str) -> str:
    return re.sub(r"[^\w]", "", w.lower())


def align_to_script(script_words: list[str], spoken: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Give every script word a start/end time. Returns (words, warnings)."""
    warnings: list[str] = []
    times: list[tuple[float, float] | None] = [None] * len(script_words)
    if len(spoken) == len(script_words):
        times = [(w["start"], w["end"]) for w in spoken]
        mismatches = sum(1 for a, b in zip(script_words, spoken) if _norm(a) != _norm(b["text"]))
        if mismatches:
            warnings.append(f"{mismatches} words differ in spelling between script and alignment (counts match, kept order)")
    else:
        warnings.append(f"Word count differs: script {len(script_words)}, audio {len(spoken)}; aligned with fuzzy matching")
        sm = difflib.SequenceMatcher(a=[_norm(w) for w in script_words], b=[_norm(w["text"]) for w in spoken], autojunk=False)
        for block in sm.get_matching_blocks():
            for k in range(block.size):
                w = spoken[block.b + k]
                times[block.a + k] = (w["start"], w["end"])
        _interpolate(script_words, times)
    words = [
        {"idx": i, "text": t, "start": round(times[i][0], 3), "end": round(times[i][1], 3)}
        for i, t in enumerate(script_words)
    ]
    return words, warnings


def _interpolate(script_words: list[str], times: list[tuple[float, float] | None]) -> None:
    """Fill gaps between known word times, spreading by character length."""
    n = len(times)
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else 0.0
        right = times[j][0] if j < n else left + 0.35 * (j - i)
        lens = [max(1, len(script_words[k])) for k in range(i, j)]
        total = sum(lens)
        t = left
        for k, ln in zip(range(i, j), lens):
            d = (right - left) * ln / total
            times[k] = (t, t + d)
            t += d
        i = j


# --- pause trimming ---------------------------------------------------------

def trim_pauses(wav_in: Path, wav_out: Path, words: list[dict[str, Any]], max_pause: float = 0.45,
                lead: float = 0.12, tail: float = 0.35, fade_s: float = 0.008) -> tuple[list[dict[str, Any]], float]:
    """Shorten silences between words to max_pause and shift word timings to match."""
    with wave.open(str(wav_in), "rb") as w:
        params = w.getparams()
        rate = w.getframerate()
        samples = array.array("h", w.readframes(w.getnframes()))
    if params.sampwidth != 2 or params.nchannels != 1:
        raise VoiceError("trim_pauses expects mono 16-bit wav")
    total = len(samples) / rate

    cuts: list[tuple[float, float]] = []
    if words and words[0]["start"] > lead:
        cuts.append((0.0, words[0]["start"] - lead))
    for a, b in zip(words, words[1:]):
        gap = b["start"] - a["end"]
        if gap > max_pause:
            cuts.append((a["end"] + max_pause / 2, b["start"] - max_pause / 2))
    if words and total - words[-1]["end"] > tail:
        cuts.append((words[-1]["end"] + tail, total))

    def removed_before(t: float) -> float:
        return sum(min(e, t) - s for s, e in cuts if s < t)

    out = array.array("h")
    pos = 0.0
    fade_n = int(fade_s * rate)
    for s, e in cuts + [(total, total)]:
        seg = samples[int(pos * rate):int(s * rate)]
        if fade_n and len(seg) > 2 * fade_n:
            for k in range(fade_n):  # fade edges so splices don't click
                g = k / fade_n
                seg[k] = int(seg[k] * g)
                seg[-1 - k] = int(seg[-1 - k] * g)
        out.extend(seg)
        pos = e
    with wave.open(str(wav_out), "wb") as w:
        w.setparams(params)
        w.writeframes(out.tobytes())

    shifted = [
        {**wd, "start": round(wd["start"] - removed_before(wd["start"]), 3),
         "end": round(wd["end"] - removed_before(wd["end"]), 3)}
        for wd in words
    ]
    return shifted, len(out) / rate


# --- speed ------------------------------------------------------------------

def speed_factor(cfg: dict[str, Any]) -> float:
    """How much faster than ElevenLabs' natural pace to play the voice (1.0 = unchanged), kept to 0.8-1.3."""
    try:
        f = float(cfg.get("speed", 1.0))
    except (TypeError, ValueError):
        f = 1.0
    return min(1.3, max(0.8, f))


def speed_up(wav_in: Path, wav_out: Path, words: list[dict[str, Any]], factor: float) -> tuple[list[dict[str, Any]], float]:
    """Speed the voice up (pitch unchanged) and scale every word timing to match, so pictures stay in sync.
    Eleven v3/v4 have no speed setting, so this is done afterwards with FFmpeg."""
    before = ffmpeg.duration(wav_in)
    ffmpeg.change_speed(wav_in, wav_out, factor)
    after = ffmpeg.duration(wav_out)
    ratio = after / before if before else 1 / factor  # the measured ratio keeps timings exact
    scaled = [{**w, "start": round(w["start"] * ratio, 3), "end": round(w["end"] * ratio, 3)} for w in words]
    return scaled, after


# --- generation -------------------------------------------------------------

def uses_style(model_id: str) -> bool:
    """Eleven v3/v4 only take stability and similarity; style, speed and speaker boost are older-model settings."""
    return not model_id.startswith(("eleven_v3", "eleven_v4"))


def voice_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "stability": cfg.get("stability", 0.5),
        "similarity_boost": cfg.get("similarity_boost", 0.9),
    }
    if uses_style(cfg.get("model_id", "eleven_v4")):
        settings.update(style=cfg.get("style", 0.0), use_speaker_boost=True)
    return settings


def _tts_request(api_key: str, voice_id: str, cfg: dict[str, Any], text: str,
                 previous_text: str | None, next_text: str | None,
                 previous_ids: list[str] | None = None) -> tuple[dict[str, Any], str | None]:
    """Returns (response json, request id). Request ids let later chunks continue the same delivery."""
    body = {
        "text": text,
        "model_id": cfg.get("model_id", "eleven_v4"),
        "voice_settings": voice_settings(cfg),
    }
    if previous_ids:
        body["previous_request_ids"] = previous_ids[-3:]  # request stitching: smoother joins than previous_text
    elif previous_text:
        body["previous_text"] = previous_text[-1000:]
    if next_text:
        body["next_text"] = next_text[:1000]
    url = f"{API}/text-to-speech/{voice_id}/with-timestamps"
    params = {"output_format": cfg.get("output_format", "mp3_44100_128")}
    for attempt in range(4):
        try:
            r = httpx.post(url, params=params, json=body, headers={"xi-api-key": api_key}, timeout=300)
        except httpx.TransportError as e:
            if attempt == 3:
                raise VoiceError(f"ElevenLabs connection failed: {e}") from e
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            return r.json(), r.headers.get("request-id")
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(2 ** (attempt + 1))
            continue
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        raise VoiceError(f"ElevenLabs error {r.status_code}: {detail}")
    raise VoiceError("ElevenLabs request failed")


def preview_text(text: str, seconds: float = 30, wpm: float = 180) -> str:
    """The opening of the script, about `seconds` long, ending at a sentence end when possible."""
    words = text.split()
    target = max(1, round(seconds * wpm / 60))
    is_end = [bool(re.search(r"[.!?…][\"'”’)]*$", w)) for w in words]
    end = min(target, len(words))
    ahead = [i for i in range(end - 1, min(len(words), int(target * 1.3))) if is_end[i]]
    behind = [i for i in range(end // 2, end) if is_end[i]]
    if ahead:  # run on to the end of the sentence
        end = ahead[0] + 1
    elif behind:  # or stop at the last full sentence
        end = behind[-1] + 1
    # Keep paragraph breaks so the voice pauses where the full read would.
    spans = [m.span() for m in re.finditer(r"\S+", text)]
    return text[:spans[end - 1][1]].strip()


def preview(text: str, out_path: Path, api_key: str, cfg: dict[str, Any]) -> float:
    """Generate a short sample (no timings, no trimming) at the narration speed. Returns its length in seconds."""
    resp, _ = _tts_request(api_key, cfg.get("voice_id", DEFAULT_JOSH_ID), cfg, text, None, None)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    factor = speed_factor(cfg)
    if factor == 1.0:
        out_path.write_bytes(base64.b64decode(resp["audio_base64"]))
    else:
        raw = out_path.with_name(out_path.stem + "_raw.mp3")
        raw.write_bytes(base64.b64decode(resp["audio_base64"]))
        ffmpeg.change_speed(raw, out_path, factor)
        raw.unlink(missing_ok=True)
    return ffmpeg.duration(out_path)


def generate(text: str, out_dir: Path, api_key: str, cfg: dict[str, Any],
             progress: Callable[[str, float], None] = lambda m, f: None) -> dict[str, Any]:
    """Generate the voice-over. Writes voice.wav (master), voice.mp3, alignment.json into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    voice_id = cfg.get("voice_id", DEFAULT_JOSH_ID)
    chunks = chunk_text(text, cfg.get("chunk_chars", 4000))
    raw: list[dict[str, Any]] = []
    wavs: list[Path] = []
    spoken: list[dict[str, Any]] = []
    offset = 0.0
    request_ids: list[str] = []
    for i, chunk in enumerate(chunks):
        progress(f"Generating audio chunk {i + 1} of {len(chunks)}", i / (len(chunks) + 1))
        prev_t = chunks[i - 1] if i > 0 else None
        next_t = chunks[i + 1] if i + 1 < len(chunks) else None
        stitch = request_ids if len(request_ids) == i else None  # only if every earlier chunk has an id
        resp, request_id = _tts_request(api_key, voice_id, cfg, chunk, prev_t, next_t, stitch)
        if request_id:
            request_ids.append(request_id)
        mp3 = out_dir / f"chunk_{i:02d}.mp3"
        mp3.write_bytes(base64.b64decode(resp["audio_base64"]))
        wav = out_dir / f"chunk_{i:02d}.wav"
        ffmpeg.to_wav(mp3, wav)
        alignment = resp.get("alignment") or resp.get("normalized_alignment")
        if not alignment:
            raise VoiceError("ElevenLabs returned no alignment data")
        spoken.extend(chars_to_words(alignment, offset))
        raw.append({"chunk": i, "offset": offset, "alignment": alignment})
        offset += ffmpeg.duration(wav)
        wavs.append(wav)

    progress("Joining audio and computing word timings", len(chunks) / (len(chunks) + 1))
    (out_dir / "alignment.json").write_text(json.dumps(raw), encoding="utf-8")
    joined = out_dir / "voice_raw.wav"
    if len(wavs) == 1:
        joined.write_bytes(wavs[0].read_bytes())
    else:
        ffmpeg.concat_wavs(wavs, joined)

    words, warnings = align_to_script(text.split(), spoken)
    master = out_dir / "voice.wav"
    if cfg.get("trim_pauses", True):
        words, dur = trim_pauses(joined, master, words, cfg.get("max_pause_s", 0.45))
    else:
        master.write_bytes(joined.read_bytes())
        dur = ffmpeg.duration(master)
    factor = speed_factor(cfg)
    if factor != 1.0:
        progress(f"Speeding up the narration to {factor:g}x", len(chunks) / (len(chunks) + 1))
        natural = out_dir / "voice_natural.wav"
        master.replace(natural)
        words, dur = speed_up(natural, master, words, factor)
        natural.unlink(missing_ok=True)
    ffmpeg.wav_to_mp3(master, out_dir / "voice.mp3")
    for p in wavs:
        p.unlink(missing_ok=True)
    progress("Done", 1.0)
    return {"audio_path": str(master), "duration": round(dur, 3), "words": words, "warnings": warnings}
