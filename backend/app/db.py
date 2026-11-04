"""SQLite storage: connection handling, migrations and repository functions.

Structured data lives here; media (audio, images, video) lives on disk under projects/<slug>/.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.config import DB_PATH, load_config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_db_path: Path = DB_PATH


def set_db_path(path: Path) -> None:
    """Point the app at a different database (used by tests)."""
    global _db_path
    _db_path = path


def connect() -> sqlite3.Connection:
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate() -> None:
    with tx() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
        done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (path.name,))


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


def _rows(rs: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rs]


# --- projects ---------------------------------------------------------------

def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "video"


FORMATS = ("story", "topic", "list")


def create_project(title: str, idea_id: int | None = None, format: str = "story") -> dict[str, Any]:
    with tx() as conn:
        base = slugify(title)
        slug, n = base, 2
        while conn.execute("SELECT 1 FROM projects WHERE slug = ?", (slug,)).fetchone():
            slug, n = f"{base}-{n}", n + 1
        cur = conn.execute(
            "INSERT INTO projects (slug, title, idea_id, format) VALUES (?, ?, ?, ?)",
            (slug, title, idea_id, format if format in FORMATS else "story"),
        )
        if idea_id is not None:
            conn.execute("UPDATE ideas SET project_id = ? WHERE id = ?", (cur.lastrowid, idea_id))
        return _row(conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone())


def get_project(project_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        return _row(conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())


def list_projects() -> list[dict[str, Any]]:
    with tx() as conn:
        return _rows(conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall())


def update_project(project_id: int, touch: bool = True, **fields: Any) -> None:
    """touch=False leaves "last updated" alone (e.g. when only archiving)."""
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    stamp = ", updated_at = datetime('now')" if touch else ""
    with tx() as conn:
        conn.execute(
            f"UPDATE projects SET {cols}{stamp} WHERE id = ?",
            (*fields.values(), project_id),
        )


def delete_project(project_id: int) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def touch_project(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("UPDATE projects SET updated_at = datetime('now') WHERE id = ?", (project_id,))


# --- ideas ------------------------------------------------------------------

IDEA_FIELDS = ("title", "hook", "why_it_works", "category", "era", "documentation", "format")


def add_ideas(ideas: list[dict[str, Any]], source: str = "suggested") -> list[dict[str, Any]]:
    with tx() as conn:
        ids = []
        for idea in ideas:
            values = {f: idea.get(f, "") for f in IDEA_FIELDS}
            if values["format"] not in FORMATS:
                values["format"] = "story"
            cur = conn.execute(
                f"INSERT INTO ideas ({', '.join(IDEA_FIELDS)}, source) VALUES ({', '.join('?' * len(IDEA_FIELDS))}, ?)",
                (*values.values(), source),
            )
            ids.append(cur.lastrowid)
        q = f"SELECT * FROM ideas WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id"
        return _rows(conn.execute(q, ids).fetchall()) if ids else []


def list_ideas(saved_only: bool = False) -> list[dict[str, Any]]:
    q = "SELECT * FROM ideas"
    if saved_only:
        q += " WHERE saved = 1"
    with tx() as conn:
        return _rows(conn.execute(q + " ORDER BY id DESC").fetchall())


def get_idea(idea_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        return _row(conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone())


def set_idea_saved(idea_id: int, saved: bool) -> None:
    with tx() as conn:
        conn.execute("UPDATE ideas SET saved = ? WHERE id = ?", (int(saved), idea_id))


def used_idea_titles() -> list[str]:
    """Titles of ideas that already became projects, so Claude can avoid repeats."""
    with tx() as conn:
        rows = conn.execute(
            "SELECT title FROM projects UNION SELECT title FROM ideas WHERE project_id IS NOT NULL"
        ).fetchall()
        return [r["title"] for r in rows]


# --- research + scripts -----------------------------------------------------

def save_research(project_id: int, content: str, sources: list[dict[str, str]]) -> dict[str, Any]:
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO research_briefs (project_id, content, sources) VALUES (?, ?, ?)",
            (project_id, content, json.dumps(sources)),
        )
        touch_project(conn, project_id)
        return _row(conn.execute("SELECT * FROM research_briefs WHERE id = ?", (cur.lastrowid,)).fetchone())


def latest_research(project_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        r = _row(conn.execute(
            "SELECT * FROM research_briefs WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,)
        ).fetchone())
    if r:
        r["sources"] = json.loads(r["sources"])
    return r


def save_script(project_id: int, text: str, source: str, instruction: str | None = None) -> dict[str, Any]:
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO script_versions (project_id, text, source, instruction, word_count) VALUES (?, ?, ?, ?, ?)",
            (project_id, text, source, instruction, len(text.split())),
        )
        touch_project(conn, project_id)
        return _row(conn.execute("SELECT * FROM script_versions WHERE id = ?", (cur.lastrowid,)).fetchone())


def current_script(project_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        return _row(conn.execute(
            "SELECT * FROM script_versions WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,)
        ).fetchone())


def get_script_version(version_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        return _row(conn.execute("SELECT * FROM script_versions WHERE id = ?", (version_id,)).fetchone())


def list_script_versions(project_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return _rows(conn.execute(
            "SELECT id, source, instruction, word_count, created_at FROM script_versions "
            "WHERE project_id = ? ORDER BY id DESC",
            (project_id,),
        ).fetchall())


def add_revision_message(project_id: int, role: str, content: str, edits: list | None = None) -> dict[str, Any]:
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO revision_messages (project_id, role, content, edits) VALUES (?, ?, ?, ?)",
            (project_id, role, content, json.dumps(edits) if edits is not None else None),
        )
        return _row(conn.execute("SELECT * FROM revision_messages WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_revision_messages(project_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        rows = _rows(conn.execute(
            "SELECT * FROM revision_messages WHERE project_id = ? ORDER BY id", (project_id,)
        ).fetchall())
    for r in rows:
        r["edits"] = json.loads(r["edits"]) if r["edits"] else None
    return rows


# --- beats ------------------------------------------------------------------

def replace_beats(project_id: int, script_version_id: int, beats: list[dict[str, Any]]) -> None:
    """Replace all beats. Image prompts cascade-delete with their beats."""
    with tx() as conn:
        conn.execute("DELETE FROM beats WHERE project_id = ?", (project_id,))
        conn.executemany(
            "INSERT INTO beats (project_id, script_version_id, idx, word_start, word_end, text) VALUES (?, ?, ?, ?, ?, ?)",
            [(project_id, script_version_id, b["idx"], b["word_start"], b["word_end"], b["text"]) for b in beats],
        )
        touch_project(conn, project_id)


BEAT_UNDO_STEPS = 20


def push_beat_undo(project_id: int, snapshot: dict[str, Any]) -> None:
    """Save the state before a split or merge, keeping only the latest BEAT_UNDO_STEPS."""
    with tx() as conn:
        conn.execute("INSERT INTO beat_undo (project_id, snapshot) VALUES (?, ?)", (project_id, json.dumps(snapshot)))
        conn.execute("DELETE FROM beat_undo WHERE project_id = ? AND id NOT IN (SELECT id FROM beat_undo "
                     "WHERE project_id = ? ORDER BY id DESC LIMIT ?)", (project_id, project_id, BEAT_UNDO_STEPS))


def pop_beat_undo(project_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        r = conn.execute("SELECT id, snapshot FROM beat_undo WHERE project_id = ? ORDER BY id DESC LIMIT 1",
                         (project_id,)).fetchone()
        if not r:
            return None
        conn.execute("DELETE FROM beat_undo WHERE id = ?", (r["id"],))
    return json.loads(r["snapshot"])


def beat_undo_steps(project_id: int) -> int:
    with tx() as conn:
        return conn.execute("SELECT COUNT(*) FROM beat_undo WHERE project_id = ?", (project_id,)).fetchone()[0]


def clear_beat_undo(project_id: int) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM beat_undo WHERE project_id = ?", (project_id,))


def list_beats(project_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return _rows(conn.execute("SELECT * FROM beats WHERE project_id = ? ORDER BY idx", (project_id,)).fetchall())


# --- voice ------------------------------------------------------------------

def save_voiceover(project_id: int, script_version_id: int, audio_path: str, duration_s: float,
                   words: list[dict[str, Any]], warnings: list[str]) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM voiceovers WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM words WHERE project_id = ?", (project_id,))
        conn.execute(
            "INSERT INTO voiceovers (project_id, script_version_id, audio_path, duration_s, warnings) VALUES (?, ?, ?, ?, ?)",
            (project_id, script_version_id, audio_path, duration_s, json.dumps(warnings)),
        )
        conn.executemany(
            "INSERT INTO words (project_id, idx, text, start_s, end_s) VALUES (?, ?, ?, ?, ?)",
            [(project_id, w["idx"], w["text"], w["start"], w["end"]) for w in words],
        )
        touch_project(conn, project_id)


def get_voiceover(project_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        r = _row(conn.execute("SELECT * FROM voiceovers WHERE project_id = ?", (project_id,)).fetchone())
    if r:
        r["warnings"] = json.loads(r["warnings"])
    return r


def list_words(project_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        rows = conn.execute(
            "SELECT idx, text, start_s AS start, end_s AS end FROM words WHERE project_id = ? ORDER BY idx",
            (project_id,),
        ).fetchall()
        return _rows(rows)


# --- style + prompts --------------------------------------------------------

def save_style_guide(project_id: int, style_prefix: str, characters: list[dict[str, str]],
                     setting_notes: str | None = None, props: list[dict[str, str]] | None = None,
                     locations: list[dict[str, str]] | None = None) -> None:
    """None for setting_notes, props or locations keeps what is stored."""
    with tx() as conn:
        conn.execute(
            "INSERT INTO style_guides (project_id, style_prefix, characters, setting_notes) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(project_id) DO UPDATE SET style_prefix = excluded.style_prefix, "
            "characters = excluded.characters, created_at = datetime('now')",
            (project_id, style_prefix, json.dumps(characters), setting_notes or ""),
        )
        if setting_notes is not None:
            conn.execute("UPDATE style_guides SET setting_notes = ? WHERE project_id = ?", (setting_notes, project_id))
        if props is not None:
            conn.execute("UPDATE style_guides SET props = ? WHERE project_id = ?", (json.dumps(props), project_id))
        if locations is not None:
            conn.execute("UPDATE style_guides SET locations = ? WHERE project_id = ?", (json.dumps(locations), project_id))


def get_style_guide(project_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        r = _row(conn.execute("SELECT * FROM style_guides WHERE project_id = ?", (project_id,)).fetchone())
    if r:
        for k in ("characters", "props", "locations"):
            r[k] = json.loads(r[k])
    return r


def upsert_prompts(project_id: int, prompts: list[dict[str, Any]], edited: bool = False) -> None:
    with tx() as conn:
        conn.executemany(
            "INSERT INTO image_prompts (beat_id, project_id, batch_no, scene, label, edited, characters, things) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(beat_id) DO UPDATE SET batch_no = excluded.batch_no, scene = excluded.scene, "
            "label = excluded.label, edited = excluded.edited, "
            "characters = COALESCE(excluded.characters, image_prompts.characters), "  # keep the cast unless given
            "things = COALESCE(excluded.things, image_prompts.things)",
            [(p["beat_id"], project_id, p["batch_no"], p["scene"], p.get("label", ""), int(edited),
              json.dumps(p["characters"]) if p.get("characters") is not None else None,
              json.dumps(p["things"]) if p.get("things") is not None else None) for p in prompts],
        )
        touch_project(conn, project_id)


def set_scenes(project_id: int, scenes: dict[int, str]) -> None:
    """Change scene text by beat id, leaving labels, casts and edited flags as they are."""
    with tx() as conn:
        conn.executemany("UPDATE image_prompts SET scene = ? WHERE beat_id = ? AND project_id = ?",
                         [(scene, beat_id, project_id) for beat_id, scene in scenes.items()])
        touch_project(conn, project_id)


def set_staging(project_id: int, staging: dict[int, tuple[list[dict[str, str]] | None, dict[str, Any]]]) -> None:
    """Store {beat id: (cast, things)}; a cast of None keeps the stored one."""
    with tx() as conn:
        conn.executemany(
            "UPDATE image_prompts SET characters = COALESCE(?, characters), things = ? WHERE beat_id = ? AND project_id = ?",
            [(json.dumps(c) if c is not None else None, json.dumps(t), beat_id, project_id)
             for beat_id, (c, t) in staging.items()])


def done_batches(project_id: int) -> list[int]:
    with tx() as conn:
        rows = conn.execute("SELECT batch_no FROM prompt_batches WHERE project_id = ? AND done = 1 ORDER BY batch_no",
                            (project_id,)).fetchall()
    return [r["batch_no"] for r in rows]


def set_batch_done(project_id: int, batch_no: int, done: bool) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO prompt_batches (project_id, batch_no, done) VALUES (?, ?, ?) "
            "ON CONFLICT(project_id, batch_no) DO UPDATE SET done = excluded.done",
            (project_id, batch_no, int(done)),
        )


def list_prompts(project_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        rows = _rows(conn.execute(
            "SELECT p.*, b.idx, b.text AS beat_text, b.word_start, b.word_end FROM image_prompts p "
            "JOIN beats b ON b.id = p.beat_id WHERE p.project_id = ? ORDER BY b.idx",
            (project_id,),
        ).fetchall())
    for r in rows:
        r["characters"] = json.loads(r["characters"]) if r["characters"] is not None else None
        r["things"] = json.loads(r["things"]) if r["things"] is not None else None
    return rows


# --- images -----------------------------------------------------------------

def replace_batch_images(project_id: int, batch_no: int, images: list[dict[str, Any]]) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM images WHERE project_id = ? AND batch_no = ?", (project_id, batch_no))
        conn.executemany(
            "INSERT INTO images (project_id, batch_no, path, sort_key, sort_source, position) VALUES (?, ?, ?, ?, ?, ?)",
            [(project_id, batch_no, im["path"], im["sort_key"], im["sort_source"], im.get("position", i))
             for i, im in enumerate(images)],
        )
        touch_project(conn, project_id)


def list_images(project_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return _rows(conn.execute(
            "SELECT * FROM images WHERE project_id = ? ORDER BY batch_no, position", (project_id,)
        ).fetchall())


def reorder_batch(project_id: int, batch_no: int, paths: list[str | None]) -> None:
    with tx() as conn:
        for i, p in enumerate(paths):
            if p is None:
                continue
            conn.execute(
                "UPDATE images SET position = ? WHERE project_id = ? AND batch_no = ? AND path = ?",
                (i, project_id, batch_no, p),
            )


# --- shots + publish --------------------------------------------------------

def replace_shots(project_id: int, shots: list[dict[str, Any]]) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM shots WHERE project_id = ?", (project_id,))
        conn.executemany(
            "INSERT INTO shots (project_id, idx, image_path, start_frame, end_frame, scale, beat_ids) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(project_id, i, s["image"], s["start_frame"], s["end_frame"], s["scale"], json.dumps(s["beat_ids"]))
             for i, s in enumerate(shots)],
        )


def list_shots(project_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        rows = _rows(conn.execute("SELECT * FROM shots WHERE project_id = ? ORDER BY idx", (project_id,)).fetchall())
    for r in rows:
        r["beat_ids"] = json.loads(r["beat_ids"])
    return rows


def save_publish_meta(project_id: int, content: dict[str, Any]) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO publish_meta (project_id, content) VALUES (?, ?) "
            "ON CONFLICT(project_id) DO UPDATE SET content = excluded.content, created_at = datetime('now')",
            (project_id, json.dumps(content)),
        )


def get_publish_meta(project_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        r = conn.execute("SELECT content FROM publish_meta WHERE project_id = ?", (project_id,)).fetchone()
    return json.loads(r["content"]) if r else None


# --- shorts + social posts --------------------------------------------------

def get_short(project_id: int) -> dict[str, Any]:
    with tx() as conn:
        r = _row(conn.execute("SELECT * FROM shorts WHERE project_id = ?", (project_id,)).fetchone())
    if not r:
        return {"project_id": project_id, "title": "", "caption": "", "hashtags": [], "youtube_url": "",
                "rendered_at": None, "duration_s": None, "cut_s": None, "cut_key": None}
    r["hashtags"] = json.loads(r["hashtags"])
    return r


def save_short(project_id: int, **fields: Any) -> dict[str, Any]:
    """Update some of title, caption, hashtags, youtube_url, rendered_at, duration_s, cut_s, cut_key."""
    if "hashtags" in fields:
        fields["hashtags"] = json.dumps(fields["hashtags"])
    with tx() as conn:
        conn.execute("INSERT OR IGNORE INTO shorts (project_id) VALUES (?)", (project_id,))
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE shorts SET {cols} WHERE project_id = ?", (*fields.values(), project_id))
    return get_short(project_id)


def add_social_post(project_id: int, platform: str, status: str, post_id: str | None = None,
                    url: str | None = None, error: str | None = None, rendered_at: str | None = None) -> dict[str, Any]:
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO social_posts (project_id, platform, status, post_id, url, error, rendered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, platform, status, post_id, url, error, rendered_at),
        )
        return _row(conn.execute("SELECT * FROM social_posts WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_social_posts(project_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return _rows(conn.execute(
            "SELECT * FROM social_posts WHERE project_id = ? ORDER BY id DESC", (project_id,)
        ).fetchall())


# --- status -----------------------------------------------------------------

def project_status(project_id: int) -> dict[str, Any]:
    """Which steps are done, and which are stale because an earlier input changed."""
    script = current_script(project_id)
    beats = list_beats(project_id)
    voice = get_voiceover(project_id)
    with tx() as conn:
        n_prompts = conn.execute("SELECT COUNT(*) FROM image_prompts WHERE project_id = ?", (project_id,)).fetchone()[0]
        n_images = conn.execute("SELECT COUNT(*) FROM images WHERE project_id = ?", (project_id,)).fetchone()[0]
        # Slots with a picture: extras (past a batch's last slot or past the last beat) don't count.
        size = load_config()["prompts"]["batch_size"]
        n_filled = conn.execute(
            "SELECT COUNT(DISTINCT (batch_no - 1) * ? + position) FROM images WHERE project_id = ? AND position < ? "
            "AND (batch_no - 1) * ? + position < ?", (size, project_id, size, size, len(beats))).fetchone()[0]
        n_shots = conn.execute("SELECT COUNT(*) FROM shots WHERE project_id = ?", (project_id,)).fetchone()[0]
        has_research = conn.execute("SELECT 1 FROM research_briefs WHERE project_id = ?", (project_id,)).fetchone()
    sid = script["id"] if script else None
    beats_stale = bool(beats) and beats[0]["script_version_id"] != sid
    return {
        "research": bool(has_research),
        "script": script is not None,
        "script_words": script["word_count"] if script else 0,
        "beats": len(beats),
        "beats_stale": beats_stale,
        "voice": voice is not None,
        "voice_stale": voice is not None and voice["script_version_id"] != sid,
        "prompts": n_prompts,
        "prompts_missing": max(0, len(beats) - n_prompts),
        "images": n_images,
        "images_filled": n_filled,
        "images_complete": bool(beats) and n_filled >= len(beats),
        "shots": n_shots,
        "publish": get_publish_meta(project_id) is not None,
        "short": get_short(project_id)["rendered_at"] is not None,
        "short_posts": len({p["platform"] for p in list_social_posts(project_id) if p["status"] == "posted"}),
    }
