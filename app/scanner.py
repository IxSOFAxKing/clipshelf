"""Watches CLIPS_DIR by polling (works on SMB/NFS/Syncthing folders, where
inotify does not) and keeps the database in step with the files on disk."""
import logging
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config, db, games, library, media, settings

log = logging.getLogger("clipshelf.scanner")

SETTLE_SECONDS = 4        # size must be unchanged this long before ingesting
OLD_FILE_SECONDS = 120    # files untouched this long are ingested immediately
STEAM_RETRY_SECONDS = 600


class Scanner:
    def __init__(self) -> None:
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}   # rel path -> {size, mtime, since, fails}
        self._steam_retry_at = 0.0
        self.status = {"last_scan": None, "clips_dir_ok": True, "pending": 0, "unreadable": 0}

    def start(self) -> None:
        threading.Thread(target=self._run, name="scanner", daemon=True).start()

    def unreadable(self) -> list[str]:
        return sorted(path for path, p in self._pending.items() if p["fails"] >= 5)

    def trigger(self) -> None:
        self._steam_retry_at = 0.0
        self._wake.set()

    def _run(self) -> None:
        while True:
            try:
                self.scan_once()
            except Exception:
                log.exception("scan failed")
            waiting = any(p["fails"] < 5 for p in self._pending.values())
            self._wake.wait(SETTLE_SECONDS + 1 if waiting else settings.get("scan_interval"))
            self._wake.clear()

    # ------------------------------------------------------------ scan ----

    def _walk(self) -> dict[str, tuple[int, float]]:
        found: dict[str, tuple[int, float]] = {}
        root = str(config.CLIPS_DIR)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "@", "#"))]
            for name in filenames:
                if name.startswith((".", "~")) or not name.lower().endswith(config.VIDEO_EXTENSIONS):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                found[rel] = (st.st_size, st.st_mtime)
        return found

    def scan_once(self) -> None:
        with self._lock:
            self._scan()
        self.status["last_scan"] = datetime.now().isoformat(timespec="seconds")

    def _scan(self) -> None:
        if not config.CLIPS_DIR.is_dir():
            if self.status["clips_dir_ok"]:
                log.warning("Clips folder %s is not available", config.CLIPS_DIR)
            self.status["clips_dir_ok"] = False
            return
        self.status["clips_dir_ok"] = True
        found = self._walk()
        now = time.time()

        with db.connect() as conn:
            # Highlights have their own file in the data folder, so they don't follow the scan.
            known = {r["path"]: r for r in conn.execute(
                "SELECT id, path, size, mtime, missing FROM clips WHERE source_path IS NULL")}
            for path, row in known.items():
                if path not in found:
                    if not row["missing"]:
                        conn.execute("UPDATE clips SET missing = 1 WHERE id = ?", (row["id"],))
                        log.info("Clip file gone: %s", path)
                elif row["missing"] == 1:   # 2 = removed from the library by hand; stays hidden
                    conn.execute("UPDATE clips SET missing = 0 WHERE id = ?", (row["id"],))

        todo = []
        for path, (size, mtime) in sorted(found.items()):
            row = known.get(path)
            if row and (row["missing"] == 2 or (row["size"] == size and abs(row["mtime"] - mtime) < 2)):
                self._pending.pop(path, None)
                continue
            p = self._pending.get(path)
            if not p or p["size"] != size or p["mtime"] != mtime:
                p = self._pending[path] = {"size": size, "mtime": mtime, "since": now, "fails": 0}
            settled = now - p["since"] >= SETTLE_SECONDS or now - mtime >= OLD_FILE_SECONDS
            # Unreadable files are retried a few times, then left until they change.
            if settled and size > 0 and p["fails"] < 5:
                todo.append(path)
        for path in list(self._pending):
            if path not in found:
                del self._pending[path]

        for path in todo:
            size, mtime = found[path]
            try:
                ok = self._ingest(path, size, mtime)
            except Exception:
                log.exception("Could not import %s", path)
                ok = False
            if ok:
                self._pending.pop(path, None)
            else:
                self._pending[path]["fails"] += 1
                if self._pending[path]["fails"] == 5:
                    log.warning("Giving up on %s (not a readable video); will retry if it changes", path)

        self.status["pending"] = sum(1 for p in self._pending.values() if p["fails"] < 5)
        self.status["unreadable"] = sum(1 for p in self._pending.values() if p["fails"] >= 5)

        if settings.get("steam_lookup") and time.time() >= self._steam_retry_at:
            self._lookup_pending_games()
        with db.connect() as conn:
            for gid in db.prune_empty_games(conn):
                library.remove_art_files(gid)

    # ---------------------------------------------------------- ingest ----

    def _ingest(self, path: str, size: int, mtime: float) -> bool:
        full = config.CLIPS_DIR / path
        info = media.probe(full)
        if not info:
            return False
        filename = Path(path).name

        with db.connect() as conn:
            row = conn.execute("SELECT id FROM clips WHERE path = ?", (path,)).fetchone()
            moved = None
            if not row:
                # Same file under a new folder/name keeps its ID (and share link).
                for cand in conn.execute(
                    "SELECT id, path FROM clips WHERE size = ? AND filename = ? AND missing != 2 AND source_path IS NULL", (size, filename)
                ):
                    if not (config.CLIPS_DIR / cand["path"]).exists():
                        moved = cand
                        break
        clip_id = row["id"] if row else moved["id"] if moved else secrets.token_urlsafe(8)

        media.make_thumbnail(full, config.THUMBS_DIR / f"{clip_id}.jpg", info["duration"])
        merged = 0
        merged_path = config.MEDIA_DIR / f"{clip_id}.mp4"
        if settings.get("merge_audio_tracks") and info["audio_tracks"] > 1:
            merged = int(media.render(full, merged_path, info["audio_tracks"], merge=True))
        if not merged:
            merged_path.unlink(missing_ok=True)

        media_cols = (size, mtime, info["duration"], info["width"], info["height"],
                      info["vcodec"], info["audio_tracks"], merged)
        with db.connect() as conn:
            if row or moved:
                conn.execute(
                    "UPDATE clips SET path = ?, filename = ?, missing = 0, size = ?, mtime = ?, duration = ?, "
                    "width = ?, height = ?, vcodec = ?, audio_tracks = ?, merged_audio = ?, thumb_custom = 0, "
                    "trim_start = NULL, trim_end = NULL, orig_duration = NULL, served_vcodec = NULL, "   # file changed: trim no longer applies
                    "thumb_v = thumb_v + 1 WHERE id = ?",
                    (path, filename, *media_cols, clip_id),
                )
                if moved:   # highlights cut from this file follow it
                    conn.execute("UPDATE clips SET source_path = ?, path = ? || '#' || id WHERE source_path = ?",
                                 (path, path, moved["path"]))
                log.info("%s clip %s", "Moved" if moved else "Updated", path)
                return True
            game, when = games.parse_clip_path(path)
            recorded = when or datetime.fromtimestamp(mtime)
            game_id = db.get_or_create_game(conn, game) if game else None
            if game_id:  # an existing game may spell the name better than the file does
                game = conn.execute("SELECT name FROM games WHERE id = ?", (game_id,)).fetchone()["name"]
            conn.execute(
                "INSERT INTO clips (id, path, filename, title, game_id, size, mtime, duration, width, height, "
                "vcodec, audio_tracks, merged_audio, recorded_at, visibility) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (clip_id, path, filename, games.default_title(path, game, when), game_id, *media_cols,
                 recorded.isoformat(timespec="seconds"), settings.get("default_visibility")),
            )
        log.info("Imported %s (game: %s)", path, game or "none")
        return True

    # ----------------------------------------------------------- steam ----

    def _lookup_pending_games(self) -> None:
        with db.connect() as conn:
            pending = conn.execute("SELECT id, name FROM games WHERE lookup_status = 'pending'").fetchall()
        for g in pending:
            try:
                match = games.best_match(g["name"], games.steam_search(g["name"]))
            except Exception as exc:
                log.warning("Steam lookup failed (%s); retrying in %d min", exc, STEAM_RETRY_SECONDS // 60)
                self._steam_retry_at = time.time() + STEAM_RETRY_SECONDS
                return
            with db.connect() as conn:
                if not match:
                    conn.execute("UPDATE games SET lookup_status = 'none' WHERE id = ? AND lookup_status = 'pending'", (g["id"],))
                    log.info("No Steam match for '%s'", g["name"])
            if not match:
                if library.sgdb_auto_art(g["id"], g["name"]):
                    log.info("Took artwork for '%s' from SteamGridDB", g["name"])
                continue
            with db.connect() as conn:
                conn.execute(
                    "UPDATE games SET steam_appid = ?, steam_name = ?, lookup_status = 'matched' "
                    "WHERE id = ? AND lookup_status = 'pending'",
                    (match["appid"], match["name"], g["id"]),
                )
                # File names lose punctuation ("Counter Strike 2"); show Steam's spelling
                # when it is the same name.
                if games.norm(match["name"]) == games.norm(g["name"]) and match["name"] != g["name"]:
                    renamed = conn.execute("UPDATE OR IGNORE games SET name = ? WHERE id = ?", (match["name"], g["id"]))
                    if renamed.rowcount:   # carry the spelling into titles made from the file name
                        prefix = g["name"] + " · "
                        conn.execute(
                            "UPDATE clips SET title = ? || substr(title, ?) WHERE game_id = ? AND substr(title, 1, ?) = ?",
                            (match["name"] + " · ", len(prefix) + 1, g["id"], len(prefix), prefix))
            log.info("Matched '%s' to Steam app %s (%s)", g["name"], match["appid"], match["name"])
            library.refresh_game(g["id"], match.get("image", ""))
            time.sleep(1)  # be polite to the store API


scanner = Scanner()
