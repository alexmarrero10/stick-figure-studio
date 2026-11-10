"""Order imported Google Flow images.

Prompts are titled "Victorian London street" (unique within a batch), and Flow names each download
after that title, so the import matches the file name to its slot and puts the slot number in front.
Older downloads named "7 - Victorian London street" use that number directly. Images matching
neither are ordered by creation time embedded in the file (EXIF, PNG text chunks, XMP),
then file modified time, then natural filename order, and fill the slots that are left.
"""
from __future__ import annotations

import io
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from PIL import Image

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME_DIGITIZED = 0x9004
EXIF_DATETIME = 0x0132
EXIF_IFD = 0x8769

XMP_DATE = re.compile(
    rb"(?:xmp:CreateDate|exif:DateTimeOriginal|photoshop:DateCreated|xmp:ModifyDate)"
    rb"(?:=\"|>)([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+(?:Z|[+-][0-9:]+)?)"
)
C2PA_WHEN = re.compile(rb"\"when\"\s*:\s*\"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+(?:Z|[+-][0-9:]+)?)\"")


def _parse_dt(s: str) -> float | None:
    s = s.strip().rstrip("\x00")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).timestamp()
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


class SlotGuard:
    """Decides which incoming images to keep when adding to a batch that may already have some.

    An image is skipped when a file with the same name is already there, when its number's slot is
    already filled, when its number is past the end of the batch, or (for unnumbered images) when
    every slot is already filled. Whatever is accepted counts as filling its slot from then on."""

    def __init__(self, folder: Path, filled: set[int], slots: int):
        self.names = {p.name.lower() for p in folder.iterdir() if p.is_file()} if folder.exists() else set()
        self.filled = set(filled)  # 1-based slot numbers that already have a picture
        self.slots = slots
        self.added: list[str] = []
        self.skipped: list[str] = []

    def accept(self, name: str) -> bool:
        n = label_number(name)
        free = self.slots - len(self.filled)
        if (name.lower() in self.names or (n and (n in self.filled or n > self.slots))
                or (not n and free <= 0)):
            self.skipped.append(name)
            return False
        self.names.add(name.lower())
        self.filled.add(n if n else min(i for i in range(1, self.slots + 1) if i not in self.filled))
        self.added.append(name)
        return True


def extract_zip(data: bytes, folder: Path, accept: Callable[[str], bool] = lambda name: True,
                rename: Callable[[str], str] = lambda name: name) -> list[str]:
    """Write the images inside a zip into folder, flattening any subfolders. Each file keeps the
    time stored in the zip as its modified time. rename(name) gives the name to save it under, and
    accept(name) can veto a file. Returns the saved file names."""
    saved: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = Path(info.filename.replace("\\", "/")).name
            if (info.is_dir() or name.startswith(".") or "__MACOSX" in info.filename
                    or Path(name).suffix.lower() not in IMAGE_EXTS):
                continue
            name = rename(name)
            if not accept(name):
                continue
            dst = folder / name
            k = 1
            while dst.name in saved:  # same name in two subfolders of the zip
                dst = folder / f"{Path(name).stem} ({k}){Path(name).suffix}"
                k += 1
            dst.write_bytes(z.read(info))
            try:
                t = datetime(*info.date_time).timestamp()
                os.utime(dst, (t, t))
            except (ValueError, OverflowError, OSError):
                pass
            saved.append(dst.name)
    return saved


def embedded_creation_time(path: Path) -> float | None:
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            sub = exif.get_ifd(EXIF_IFD) if exif else {}
            for tag, src in ((EXIF_DATETIME_ORIGINAL, sub), (EXIF_DATETIME_DIGITIZED, sub), (EXIF_DATETIME, exif)):
                if src and tag in src:
                    t = _parse_dt(str(src[tag]))
                    if t:
                        return t
            for key in ("Creation Time", "creation_time", "date:create", "CreationTime"):
                if key in im.info:
                    t = _parse_dt(str(im.info[key]))
                    if t:
                        return t
            xmp = im.info.get("xmp") or im.info.get("XML:com.adobe.xmp")
            if isinstance(xmp, str):
                xmp = xmp.encode("utf-8", "ignore")
            if xmp:
                m = XMP_DATE.search(xmp)
                if m:
                    return _parse_dt(m.group(1).decode())
    except OSError:
        return None
    # Fall back to scanning the raw bytes (XMP packets / C2PA manifests Pillow didn't expose).
    try:
        with open(path, "rb") as f:
            head = f.read(512 * 1024)
    except OSError:
        return None
    for rx in (XMP_DATE, C2PA_WHEN):
        m = rx.search(head)
        if m:
            t = _parse_dt(m.group(1).decode())
            if t:
                return t
    return None


# "7 - Victorian London street.png", "07_Victorian_London_street (1).png", "7. Vault.jpg"
LABEL_NUMBER = re.compile(r"^\s*(\d{1,3})(?!\d)\s*[-_.):\u2013\u2014 ]")


def label_number(name: str) -> int | None:
    m = LABEL_NUMBER.match(name)
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def numbered(name: str, number: int | None) -> str:
    """The file name with its slot number replaced ("12_-_Vault.jpg" -> "3 - Vault.jpg"), or with no
    number at all for None. The number is what places an image, so renaming moves it for good."""
    m = LABEL_NUMBER.match(name)
    rest = (name[m.end():] if m else name).lstrip(" -_.)") or "image" + Path(name).suffix
    return f"{number} - {rest}" if number else rest


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z' ]+", " ", text.lower().replace("_", " ")).split())


def slot_for_title(name: str, titles: dict[int, str]) -> int | None:
    """The 1-based slot whose prompt title this file is named after ("Oval Office desk.png", "Oval_Office_desk
    (1).jpg", "Oval Office desk 7f3a.png"), or None. Files that already start with a number keep it."""
    if label_number(name):
        return None
    stem = re.sub(r"\s*\(\d+\)$", "", Path(name).stem)
    k = _words(stem)
    if not k:
        return None
    keys = {n: _words(t) for n, t in titles.items() if _words(t)}
    exact = [n for n, t in keys.items() if t == k]
    if len(exact) == 1:
        return exact[0]
    # Flow may cut a long name short or add something after it.
    near = [n for n, t in keys.items() if k.startswith(t + " ") or t.startswith(k + " ")]
    return near[0] if len(near) == 1 else None


def name_by_title(name: str, titles: dict[int, str]) -> str:
    """The file name with its slot number in front when it matches a prompt title, so it lands in that slot."""
    n = slot_for_title(name, titles)
    return numbered(name, n) if n else name


# (file name, read its bytes, time stored in the zip or None)
ImageEntry = tuple[str, Callable[[], bytes], "float | None"]


def _zip_time(info: zipfile.ZipInfo) -> float | None:
    try:
        return datetime(*info.date_time).timestamp()
    except (ValueError, OverflowError):
        return None


def zip_groups(z: zipfile.ZipFile, label: str, depth: int = 0) -> Iterator[tuple[str, list[ImageEntry]]]:
    """The images in a zip, grouped the way Flow downloads come: every zip inside it (one batch's download)
    and every folder of images is its own group. Inner zips are only open while their group is in use."""
    by_dir: dict[str, list[ImageEntry]] = {}
    for info in z.infolist():
        path = info.filename.replace("\\", "/")
        name = Path(path).name
        if info.is_dir() or name.startswith(".") or "__MACOSX" in path:
            continue
        suffix = Path(name).suffix.lower()
        if suffix == ".zip" and depth < 3:
            try:
                with zipfile.ZipFile(io.BytesIO(z.read(info))) as inner:
                    yield from zip_groups(inner, Path(name).stem, depth + 1)
            except zipfile.BadZipFile:
                continue
        elif suffix in IMAGE_EXTS:
            by_dir.setdefault(str(Path(path).parent), []).append(
                (name, lambda info=info: z.read(info), _zip_time(info)))
    for folder, items in by_dir.items():
        yield (label if folder in ("", ".") else f"{label}/{folder}"), items


BATCH_IN_NAME = re.compile(r"batch[\s_-]*0*(\d{1,3})(?!\d)", re.I)


def plan_group(label: str, names: list[str], titles_by_batch: dict[int, dict[int, str]]) -> list[int | None]:
    """Which batch each image of one group belongs in, or None when it can't be told. An image named after
    a prompt title that only one batch has goes there. The rest go to the group's batch: the one most of
    its images match (it must hold at least half the matched ones, so a zip of every batch thrown together
    doesn't dump strays in one place), else a batch number in the zip or folder name ("batch_03")."""
    def matches(name: str) -> list[int]:
        bare = numbered(name, None)  # old "7 - Title" files match by their title too
        return [b for b, t in titles_by_batch.items() if slot_for_title(bare, t)]

    hits = [matches(n) for n in names]
    counts: dict[int, int] = {}
    for h in hits:
        for b in h:
            counts[b] = counts.get(b, 0) + 1
    matched = sum(1 for h in hits if h)
    group: int | None = None
    if counts:
        best = max(counts.values())
        top = [b for b, c in counts.items() if c == best]
        if len(top) == 1 and best * 2 >= matched:
            group = top[0]
    if group is None:
        m = BATCH_IN_NAME.search(label)
        if m and int(m.group(1)) in titles_by_batch:
            group = int(m.group(1))
    out: list[int | None] = []
    for h in hits:
        if len(h) == 1:
            out.append(h[0])
        elif group is not None and (not h or group in h):
            out.append(group)
        else:
            out.append(None)
    return out


def rename_free(path: Path, name: str) -> Path:
    """Rename `path` to `name` in the same folder, adding " (2)", " (3)"... if that name is taken."""
    stem, suffix = Path(name).stem, Path(name).suffix
    target = path.with_name(name)
    n = 2
    while target.exists() and target.resolve() != path.resolve():
        target = path.with_name(f"{stem} ({n}){suffix}")
        n += 1
    return path.rename(target)


def natural_key(name: str) -> list[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def order_images(folder: Path) -> list[dict[str, Any]]:
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    out = []
    for p in files:
        t = embedded_creation_time(p)
        source = "metadata"
        if t is None:
            t = os.stat(p).st_mtime
            source = "mtime"
        out.append({"path": str(p), "name": p.name, "sort_key": t, "sort_source": source,
                    "number": label_number(p.name)})
    # If no file has a usable time at all, filename order is all we have.
    out.sort(key=lambda x: (x["sort_key"], natural_key(x["name"])))
    keys = [x["sort_key"] for x in out]
    if len(set(keys)) <= 1 and len(out) > 1:
        out.sort(key=lambda x: natural_key(x["name"]))
        for x in out:
            x["sort_source"] = "filename"
    return out


def assign_positions(images: list[dict[str, Any]], slots: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Give each image a 0-based slot. Numbered images go to slot number-1; when two share a number
    the newest wins and the other becomes an extra. Unnumbered images (already in time/name order)
    fill the free slots. Returns the images sorted by position, and warnings."""
    warnings: list[str] = []
    placed: dict[int, dict[str, Any]] = {}
    leftover: list[dict[str, Any]] = []
    for im in sorted((x for x in images if x["number"]), key=lambda x: -x["sort_key"]):
        pos = im["number"] - 1
        if pos >= slots:
            warnings.append(f"{im['name']} is numbered {im['number']} but this batch only has {slots} images")
            leftover.append(im)
        elif pos in placed:
            warnings.append(f"{im['name']} and {placed[pos]['name']} are both numbered {im['number']}; "
                            f"using the newer one. Remove the one you don't want.")
            leftover.append(im)
        else:
            placed[pos] = {**im, "sort_source": "label"}
    free = [i for i in range(slots) if i not in placed]
    queue = [x for x in images if not x["number"]] + sorted(leftover, key=lambda x: x["number"])
    end = max([slots, *(p + 1 for p in placed)])
    for im in queue:
        if free and not im["number"]:
            pos = free.pop(0)
        else:
            pos, end = end, end + 1
        placed[pos] = im
    out = [{**im, "position": pos} for pos, im in sorted(placed.items())]
    return out, warnings


def tie_warnings(images: list[dict[str, Any]], tolerance_s: float = 0.5) -> list[str]:
    """Flag neighbouring images whose timestamps are nearly identical (parallel generation)."""
    warnings = []
    for a, b in zip(images, images[1:]):
        if abs(b["sort_key"] - a["sort_key"]) < tolerance_s and a["sort_source"] != "filename":
            warnings.append(f"{a['name']} and {b['name']} were created within {tolerance_s}s; check their order")
    return warnings
