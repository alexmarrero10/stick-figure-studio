import array
import math
import wave

import pytest

from pipeline import ffmpeg, voice


def alignment_for(text, char_s=0.05, gaps=None):
    """Fake ElevenLabs alignment: each char takes char_s; optional extra pause after given char index."""
    gaps = gaps or {}
    chars, starts, ends = [], [], []
    t = 0.0
    for i, c in enumerate(text):
        chars.append(c)
        starts.append(round(t, 3))
        t += char_s
        ends.append(round(t, 3))
        t += gaps.get(i, 0.0)
    return {"characters": chars, "character_start_times_seconds": starts, "character_end_times_seconds": ends}


def test_chars_to_words_groups_on_whitespace():
    words = voice.chars_to_words(alignment_for("Hi there,\n\nfriend."), offset=10.0)
    assert [w["text"] for w in words] == ["Hi", "there,", "friend."]
    assert words[0]["start"] == 10.0
    assert abs(words[0]["end"] - 10.1) < 1e-9
    assert words[1]["start"] > words[0]["end"]


def test_chunk_text_preserves_words():
    paras = [" ".join(f"w{p}_{i}." for i in range(60)) for p in range(10)]
    text = "\n\n".join(paras)
    chunks = voice.chunk_text(text, max_chars=500)
    assert all(len(c) <= 500 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_align_exact_counts():
    script = "One two three.".split()
    spoken = voice.chars_to_words(alignment_for("One two three."))
    words, warnings = voice.align_to_script(script, spoken)
    assert [w["idx"] for w in words] == [0, 1, 2]
    assert warnings == []


def test_align_fuzzy_fills_missing_words():
    script = "The vault held 2.4 million dollars in cash.".split()
    # Pretend the TTS normalized "2.4" into two spoken words.
    spoken = voice.chars_to_words(alignment_for("The vault held two point four million dollars in cash."))
    words, warnings = voice.align_to_script(script, spoken)
    assert len(words) == len(script)
    assert warnings
    starts = [w["start"] for w in words]
    assert starts == sorted(starts)
    assert words[3]["start"] >= words[2]["end"] - 1e-6


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


def test_trim_pauses_shortens_gaps_and_shifts_words(tmp_path):
    src, dst = tmp_path / "in.wav", tmp_path / "out.wav"
    words = [
        {"idx": 0, "text": "a", "start": 0.5, "end": 1.0},
        {"idx": 1, "text": "b", "start": 3.0, "end": 3.5},   # 2.0 s gap → 0.45 s
        {"idx": 2, "text": "c", "start": 3.7, "end": 4.0},   # 0.2 s gap, untouched
    ]
    make_wav(src, 5.0, tone_spans=[(w["start"], w["end"]) for w in words])
    new, dur = voice.trim_pauses(src, dst, words, max_pause=0.45, lead=0.12, tail=0.35)
    assert abs(new[0]["start"] - 0.12) < 0.01
    assert abs((new[1]["start"] - new[0]["end"]) - 0.45) < 0.01
    assert abs((new[2]["start"] - new[1]["end"]) - 0.2) < 0.01
    assert abs(dur - (new[2]["end"] + 0.35)) < 0.01
    with wave.open(str(dst)) as w:
        assert abs(w.getnframes() / w.getframerate() - dur) < 0.001


def test_chunks_are_stitched_with_previous_request_ids(monkeypatch):
    sent = []

    class Resp:
        status_code = 200

        def __init__(self, n):
            self.headers = {"request-id": f"req{n}"}

        def json(self):
            return {"audio_base64": "", "alignment": {}}

    def fake_post(url, params, json, headers, timeout):
        sent.append(json)
        return Resp(len(sent))

    monkeypatch.setattr(voice.httpx, "post", fake_post)
    _, rid = voice._tts_request("k", "v", {}, "first", None, "second")
    _, _ = voice._tts_request("k", "v", {}, "second", "first", None, [rid])
    assert "previous_request_ids" not in sent[0] and sent[0]["next_text"] == "second"
    assert sent[1]["previous_request_ids"] == ["req1"] and "previous_text" not in sent[1]


def test_preview_text_stops_at_sentence_end_and_keeps_paragraphs():
    text = "One two three four. Five six seven eight nine.\n\nTen eleven twelve. Thirteen."
    # 8 words at 60 wpm = 8 s: runs on to the end of the sentence.
    assert voice.preview_text(text, seconds=8, wpm=60) == "One two three four. Five six seven eight nine."
    # 6 s: the sentence end is too far ahead, so it stops at the last full sentence.
    assert voice.preview_text(text, seconds=6, wpm=60) == "One two three four."
    assert voice.preview_text(text, seconds=4, wpm=60) == "One two three four."
    assert voice.preview_text(text, seconds=60, wpm=60) == text
    assert voice.preview_text(text, seconds=11, wpm=60) == "One two three four. Five six seven eight nine.\n\nTen eleven twelve."


def test_voice_settings_drop_style_for_v4():
    v4 = voice.voice_settings({"model_id": "eleven_v4", "stability": 0.5, "similarity_boost": 0.9, "style": 0.4})
    assert v4 == {"stability": 0.5, "similarity_boost": 0.9}
    v2 = voice.voice_settings({"model_id": "eleven_multilingual_v2", "style": 0.4})
    assert v2["style"] == 0.4 and v2["use_speaker_boost"] is True


def test_speed_factor_defaults_and_limits():
    assert voice.speed_factor({}) == 1.0
    assert voice.speed_factor({"speed": 1.1}) == 1.1
    assert voice.speed_factor({"speed": 3}) == 1.3 and voice.speed_factor({"speed": 0.2}) == 0.8
    assert voice.speed_factor({"speed": "fast"}) == 1.0


@pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg not installed")
def test_speed_up_shortens_audio_and_scales_word_times(tmp_path):
    src, out = tmp_path / "in.wav", tmp_path / "out.wav"
    make_wav(src, 11.0)
    words = [{"text": "a", "start": 1.0, "end": 1.5}, {"text": "b", "start": 10.0, "end": 10.6}]
    scaled, dur = voice.speed_up(src, out, words, 1.1)
    assert abs(dur - 10.0) < 0.05 and abs(ffmpeg.duration(out) - dur) < 0.001
    ratio = dur / 11.0  # timings follow the measured length, so they stay locked to the audio
    assert scaled[0]["start"] == pytest.approx(1.0 * ratio, abs=0.002)
    assert scaled[1]["end"] == pytest.approx(10.6 * ratio, abs=0.002) and scaled[1]["end"] <= dur


@pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg not installed")
def test_preview_trims_pauses_and_applies_speed_like_the_full_voice(tmp_path, monkeypatch):
    import base64
    src = tmp_path / "src.wav"
    make_wav(src, 6.0, tone_spans=[(0.1, 1.0), (3.0, 4.0)])  # 2 s of silence between two "sentences"
    mp3 = tmp_path / "src.mp3"
    ffmpeg.wav_to_mp3(src, mp3)
    chars = list("one two")
    starts = [0.1, 0.4, 0.7, 0.95, 3.0, 3.4, 3.7]
    alignment = {"characters": chars, "character_start_times_seconds": starts,
                 "character_end_times_seconds": [x + 0.29 for x in starts]}
    monkeypatch.setattr(voice, "_tts_request", lambda *a, **k: ({"audio_base64": base64.b64encode(mp3.read_bytes()).decode(),
                                                                 "alignment": alignment}, None))
    out = tmp_path / "preview.mp3"
    plain = voice.preview("one two", out, "key", {"trim_pauses": False, "speed": 1.0})
    trimmed = voice.preview("one two", out, "key", {"trim_pauses": True, "max_pause_s": 0.3, "speed": 1.0})
    fast = voice.preview("one two", out, "key", {"trim_pauses": True, "max_pause_s": 0.3, "speed": 1.2})
    assert plain > 5.5 and trimmed < plain - 1.5  # the long gap is cut down
    assert fast == pytest.approx(trimmed / 1.2, abs=0.1)
    assert sorted(f.name for f in tmp_path.iterdir()) == ["preview.mp3", "src.mp3", "src.wav"]  # no leftovers
