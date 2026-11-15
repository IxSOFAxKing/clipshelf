"""Trimming. The original file is never changed: a cut copy is written to
MEDIA_DIR and served instead, and the trim can be changed or removed later."""
import logging
import secrets
import shutil
import threading

from . import config, db, media, settings

log = logging.getLogger("clipshelf.trim")
MIN_LENGTH = 0.5
_slots = threading.Semaphore(1)     # one encode at a time


def source_duration(row) -> float:
    return row["orig_duration"] or row["duration"] or 0.0


def source_file(row):
    """The recording in the clips folder (for a highlight, the clip it was cut from)."""
    return config.CLIPS_DIR / (row["source_path"] or row["path"])


def served_path(row):
    """The file browsers get: the copy in MEDIA_DIR if there is one."""
    copy = config.MEDIA_DIR / f"{row['id']}.mp4"
    return copy if row["merged_audio"] and copy.is_file() else source_file(row)


def start(clip_id: str, begin: float | None, end: float | None, new: bool = False) -> None:
    """Mark the clip as processing and do the work in the background.
    `new` means the clip was just created as a highlight: if the cut fails,
    it is dropped again."""
    with db.connect() as conn:
        conn.execute("UPDATE clips SET processing = 1 WHERE id = ?", (clip_id,))
    threading.Thread(target=_run, args=(clip_id, begin, end, new), daemon=True).start()


def create_highlight(row, begin: float, end: float, title: str) -> str:
    """Add a new clip cut from `row`'s recording, leaving `row` as it is."""
    clip_id = secrets.token_urlsafe(8)
    real = row["source_path"] or row["path"]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO clips (id, path, source_path, filename, title, game_id, game_locked, size, mtime, duration, "
            "width, height, vcodec, audio_tracks, recorded_at, visibility, trim_start, trim_end, orig_duration, processing) "
            "VALUES (?,?,?,?,?,?,1,0,?,?,?,?,?,?,?,?,?,?,?,1)",
            (clip_id, f"{real}#{clip_id}", real, row["filename"], title, row["game_id"], row["mtime"], end - begin,
             row["width"], row["height"], row["vcodec"], row["audio_tracks"], row["recorded_at"],
             settings.get("default_visibility"), begin, end, source_duration(row)),
        )
    thumb = config.THUMBS_DIR / f"{row['id']}.jpg"
    if thumb.is_file():
        shutil.copyfile(thumb, config.THUMBS_DIR / f"{clip_id}.jpg")
    start(clip_id, begin, end, new=True)
    return clip_id


def _run(clip_id: str, begin: float | None, end: float | None, new: bool) -> None:
    with _slots:
        ok = False
        try:
            ok = _apply(clip_id, begin, end)
        except Exception:
            log.exception("Trim failed for %s", clip_id)
        finally:
            with db.connect() as conn:
                if new and not ok:
                    conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
                else:
                    conn.execute("UPDATE clips SET processing = 0 WHERE id = ?", (clip_id,))
            if new and not ok:
                (config.THUMBS_DIR / f"{clip_id}.jpg").unlink(missing_ok=True)


def _apply(clip_id: str, begin: float | None, end: float | None) -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not row:
        return False
    src = source_file(row)
    dest = config.MEDIA_DIR / f"{clip_id}.mp4"
    full = source_duration(row)
    merge = bool(settings.get("merge_audio_tracks")) and row["audio_tracks"] > 1
    trimming = begin is not None

    if trimming:
        exact = settings.get("trim_mode") == "exact"
        ok = media.render(src, dest, row["audio_tracks"], merge, begin, end, exact)
        if not ok and not exact:   # some files can't be cut without re-encoding
            ok = media.render(src, dest, row["audio_tracks"], merge, begin, end, True)
        if not ok:
            return False           # the clip keeps whatever it had before
    elif merge:
        if not media.render(src, dest, row["audio_tracks"], merge=True):
            return False
    else:
        dest.unlink(missing_ok=True)

    has_copy = trimming or merge
    info = media.probe(dest if has_copy else src)
    duration = info["duration"] if info else (end - begin if trimming else full)
    media.make_thumbnail(dest if has_copy else src, config.THUMBS_DIR / f"{clip_id}.jpg", duration)
    with db.connect() as conn:
        conn.execute(
            "UPDATE clips SET trim_start = ?, trim_end = ?, orig_duration = ?, duration = ?, merged_audio = ?, "
            "served_vcodec = ?, size = CASE WHEN source_path IS NULL THEN size ELSE ? END, "
            "thumb_custom = 0, thumb_v = thumb_v + 1 WHERE id = ?",
            (begin, end, full if trimming else None, duration, int(has_copy),
             info["vcodec"] if info and has_copy else None, dest.stat().st_size if has_copy else 0, clip_id),
        )
    log.info("%s %s", "Trimmed" if trimming else "Removed trim from", row["path"])
    return True
