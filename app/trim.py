"""Trimming. The original file is never changed: a cut copy is written to
MEDIA_DIR and served instead, and the trim can be changed or removed later."""
import logging
import threading

from . import config, db, media, settings

log = logging.getLogger("clipshelf.trim")
MIN_LENGTH = 0.5
_slots = threading.Semaphore(1)     # one encode at a time


def source_duration(row) -> float:
    return row["orig_duration"] or row["duration"] or 0.0


def served_path(row):
    """The file browsers get: the copy in MEDIA_DIR if there is one."""
    copy = config.MEDIA_DIR / f"{row['id']}.mp4"
    return copy if row["merged_audio"] and copy.is_file() else config.CLIPS_DIR / row["path"]


def start(clip_id: str, begin: float | None, end: float | None) -> None:
    """Mark the clip as processing and do the work in the background."""
    with db.connect() as conn:
        conn.execute("UPDATE clips SET processing = 1 WHERE id = ?", (clip_id,))
    threading.Thread(target=_run, args=(clip_id, begin, end), daemon=True).start()


def _run(clip_id: str, begin: float | None, end: float | None) -> None:
    with _slots:
        try:
            _apply(clip_id, begin, end)
        except Exception:
            log.exception("Trim failed for %s", clip_id)
        finally:
            with db.connect() as conn:
                conn.execute("UPDATE clips SET processing = 0 WHERE id = ?", (clip_id,))


def _apply(clip_id: str, begin: float | None, end: float | None) -> None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if not row:
        return
    src = config.CLIPS_DIR / row["path"]
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
            return                 # the clip keeps whatever it had before
    elif merge:
        if not media.render(src, dest, row["audio_tracks"], merge=True):
            return
    else:
        dest.unlink(missing_ok=True)

    has_copy = trimming or merge
    info = media.probe(dest if has_copy else src)
    duration = info["duration"] if info else (end - begin if trimming else full)
    media.make_thumbnail(dest if has_copy else src, config.THUMBS_DIR / f"{clip_id}.jpg", duration)
    with db.connect() as conn:
        conn.execute(
            "UPDATE clips SET trim_start = ?, trim_end = ?, orig_duration = ?, duration = ?, merged_audio = ?, "
            "served_vcodec = ?, thumb_custom = 0, thumb_v = thumb_v + 1 WHERE id = ?",
            (begin, end, full if trimming else None, duration, int(has_copy),
             info["vcodec"] if info and has_copy else None, clip_id),
        )
    log.info("%s %s", "Trimmed" if trimming else "Removed trim from", row["path"])
