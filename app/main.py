"""Clipshelf web app: JSON API, share pages and media delivery."""
import hashlib
import hmac
import html
import json
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, games, library, media, settings, sgdb
from .scanner import scanner

log = logging.getLogger("clipshelf")
STATIC = Path(__file__).parent / "static"
COOKIE = "clipshelf_session"
MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/mp4",
        ".webm": "video/webm", ".mkv": "video/x-matroska"}
MAX_UPLOAD = 15_000_000


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.init()
    db.init()
    settings.load()
    if config.PASSWORD_WAS_GENERATED:
        log.warning("ADMIN_PASSWORD is not set. Generated admin password: %s "
                    "(saved in %s/admin_password.txt)", config.ADMIN_PASSWORD, config.DATA_DIR)
    log.info("Watching %s (every %ss); data in %s", config.CLIPS_DIR, settings.get("scan_interval"), config.DATA_DIR)
    scanner.start()
    yield


app = FastAPI(title="Clipshelf", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"   # revalidate, so updates show up right away
    return resp


def background(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


# ------------------------------------------------------------------ auth ----

def _sign(expires: int) -> str:
    key = config.SECRET_KEY + settings.session_material()
    return hmac.new(key, str(expires).encode(), hashlib.sha256).hexdigest()


def is_admin(request: Request) -> bool:
    token = request.cookies.get(COOKIE, "")
    expires, _, sig = token.partition(".")
    if not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(int(expires)))


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(401, "Sign in required")


def _start_session(response: Response) -> None:
    expires = int(time.time()) + config.SESSION_DAYS * 86400
    secure = config.SECURE_COOKIES or settings.get("base_url").startswith("https://")
    response.set_cookie(COOKIE, f"{expires}.{_sign(expires)}", max_age=config.SESSION_DAYS * 86400,
                        httponly=True, samesite="lax", secure=secure)


_failed_logins: list[float] = []


def _check_password(password: str) -> None:
    now = time.time()
    _failed_logins[:] = [t for t in _failed_logins if now - t < 300]
    if len(_failed_logins) >= 10:
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    if not settings.check_password(password):
        _failed_logins.append(now)
        time.sleep(0.5)
        raise HTTPException(401, "Wrong password")


@app.post("/api/login")
def login(response: Response, body: dict = Body(...)):
    _check_password(str(body.get("password", "")))
    _start_session(response)
    return {"admin": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"admin": False}


@app.post("/api/password")
def change_password(request: Request, response: Response, body: dict = Body(...)):
    require_admin(request)
    _check_password(str(body.get("current", "")))
    new = str(body.get("new", ""))
    if len(new) < 6:
        raise HTTPException(400, "Use at least 6 characters")
    settings.set_password(new)
    _start_session(response)          # other browsers are signed out
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    admin = is_admin(request)
    out = {"admin": admin, **settings.public_values()}
    if admin:
        out.update(scanner=scanner.status, sgdb=bool(settings.sgdb_key()),
                   can_delete_files=os.access(config.CLIPS_DIR, os.W_OK))
    return out


# -------------------------------------------------------------- settings ----

@app.get("/api/settings")
def get_settings(request: Request):
    require_admin(request)
    return {"values": settings.all_values(),
            "steamgriddb_key_set": bool(settings.sgdb_key()),
            "defaults": {k: v[1] for k, v in settings.SPEC.items()},
            "clips_dir": str(config.CLIPS_DIR)}


@app.patch("/api/settings")
def patch_settings(request: Request, body: dict = Body(...)):
    require_admin(request)
    try:
        values = settings.update(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if "scan_interval" in body or "steam_lookup" in body:
        scanner.trigger()
    return {"values": values}


def _retry_unmatched() -> None:
    with db.connect() as conn:
        conn.execute("UPDATE games SET lookup_status = 'pending' WHERE lookup_status = 'none'")
    scanner.trigger()


@app.put("/api/settings/steamgriddb-key")
def set_sgdb_key(request: Request, body: dict = Body(...)):
    """Save (or, with an empty key, remove) the SteamGridDB API key."""
    require_admin(request)
    key = str(body.get("key", "")).strip()
    if key:
        try:
            sgdb.check_key(key)
        except sgdb.SgdbError as exc:
            raise HTTPException(400, str(exc))
    settings.set_sgdb_key(key)
    if key:
        _retry_unmatched()        # games Steam doesn't know can now get artwork
    return {"steamgriddb_key_set": bool(settings.sgdb_key())}


@app.post("/api/settings/test-filename")
def test_filename(request: Request, body: dict = Body(...)):
    """Show what a file name would be filed as (with an optional trial pattern)."""
    require_admin(request)
    pattern = body.get("pattern")
    if pattern:
        try:
            settings.SPEC["filename_pattern"][0](pattern)
        except ValueError as exc:
            raise HTTPException(400, f"Pattern {exc}")
    name = str(body.get("filename", "")).strip()
    game, when = games.parse_clip_path(name, pattern if pattern is not None else None)
    return {"game": game, "recorded_at": when.isoformat(timespec="seconds") if when else None,
            "title": games.default_title(name, game, when) if name else ""}


@app.get("/api/stats")
def stats(request: Request):
    require_admin(request)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS clips, COALESCE(SUM(size), 0) AS bytes, COALESCE(SUM(duration), 0) AS seconds, "
            "COALESCE(SUM(views), 0) AS views, "
            "SUM(visibility = 'private') AS private, SUM(visibility = 'unlisted') AS unlisted, "
            "SUM(visibility = 'public') AS public FROM clips WHERE missing = 0").fetchone()
        removed = conn.execute("SELECT COUNT(*) FROM clips WHERE missing = 2").fetchone()[0]
        n_games = conn.execute("SELECT COUNT(DISTINCT game_id) FROM clips WHERE missing = 0").fetchone()[0]
        unmatched = conn.execute(
            "SELECT COUNT(*) FROM games WHERE steam_appid IS NULL AND id IN "
            "(SELECT game_id FROM clips WHERE missing = 0)").fetchone()[0]
    data_bytes = 0
    for root, _, files in os.walk(config.DATA_DIR):
        for name in files:
            try:
                data_bytes += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return {**{k: row[k] or 0 for k in row.keys()}, "games": n_games, "unmatched_games": unmatched, "removed": removed,
            "data_bytes": data_bytes, "scanner": scanner.status, "unreadable": scanner.unreadable()[:50],
            "clips_dir": str(config.CLIPS_DIR)}


def _refresh_all_metadata() -> None:
    with db.connect() as conn:
        conn.execute("UPDATE games SET lookup_status = 'pending' WHERE lookup_status = 'none'")
        ids = [r["id"] for r in conn.execute("SELECT id FROM games WHERE steam_appid IS NOT NULL")]
    for gid in ids:
        library.refresh_game(gid)
        time.sleep(1)
    scanner.trigger()


def _regenerate_thumbnails() -> None:
    with db.connect() as conn:
        rows = conn.execute("SELECT id, path, duration FROM clips WHERE missing = 0 AND thumb_custom = 0").fetchall()
    for r in rows:
        if media.make_thumbnail(config.CLIPS_DIR / r["path"], config.THUMBS_DIR / f"{r['id']}.jpg", r["duration"] or 0):
            with db.connect() as conn:
                conn.execute("UPDATE clips SET thumb_v = thumb_v + 1 WHERE id = ?", (r["id"],))


def _restore_removed() -> None:
    with db.connect() as conn:
        conn.execute("UPDATE clips SET missing = 0 WHERE missing = 2")
    scanner.trigger()     # anything whose file has since gone drops out again


MAINTENANCE = {"rescan": scanner.trigger, "restore-removed": _restore_removed, "refresh-metadata": _refresh_all_metadata,
               "regenerate-thumbnails": _regenerate_thumbnails}


@app.post("/api/maintenance/{task}")
def maintenance(task: str, request: Request):
    require_admin(request)
    if task not in MAINTENANCE:
        raise HTTPException(404, "Unknown task")
    background(MAINTENANCE[task])
    return {"ok": True}


@app.post("/api/rescan")
def rescan(request: Request):
    require_admin(request)
    scanner.trigger()
    return {"ok": True}


# ----------------------------------------------------------------- clips ----

CLIP_SELECT = """
SELECT c.*, g.name AS game_name, g.steam_appid, g.steam_name, g.has_cover, g.art_v
FROM clips c LEFT JOIN games g ON g.id = c.game_id
"""
SORTS = {
    "newest": "c.recorded_at DESC",
    "oldest": "c.recorded_at ASC",
    "views": "c.views DESC, c.recorded_at DESC",
    "longest": "c.duration DESC",
    "title": "c.title COLLATE NOCASE ASC",
}


def clip_json(row, admin: bool) -> dict:
    out = {
        "id": row["id"],
        "title": row["title"],
        "duration": row["duration"],
        "width": row["width"],
        "height": row["height"],
        "recorded_at": row["recorded_at"],
        "visibility": row["visibility"],
        "views": row["views"] if admin or settings.get("show_views") else None,
        "web_playable": (row["vcodec"] or "") in media.WEB_CODECS,
        "thumb": f"/t/{row['id']}.jpg?v={row['thumb_v']}",
        "game": None,
    }
    if row["game_id"]:
        out["game"] = {"id": row["game_id"], "name": row["game_name"], "steam_appid": row["steam_appid"],
                       "steam_name": row["steam_name"],
                       "cover": f"/covers/{row['game_id']}.jpg?v={row['art_v']}" if row["has_cover"] else None}
    if admin:
        out.update(favorite=bool(row["favorite"]), filename=row["path"], size=row["size"],
                   vcodec=row["vcodec"], audio_tracks=row["audio_tracks"], thumb_custom=bool(row["thumb_custom"]))
    return out


def get_clip(clip_id: str, request: Request):
    """Fetch a clip the requester is allowed to see, else 404."""
    with db.connect() as conn:
        row = conn.execute(CLIP_SELECT + " WHERE c.id = ? AND c.missing = 0", (clip_id,)).fetchone()
    if not row or (row["visibility"] == "private" and not is_admin(request)):
        raise HTTPException(404, "Clip not found")
    return row


@app.get("/api/clips")
def list_clips(request: Request, game: str = "", q: str = "", sort: str = "",
               visibility: str = "", favorite: bool = False, limit: int = 60, offset: int = 0):
    admin = is_admin(request)
    where, args = ["c.missing = 0"], []
    if not admin:
        where.append("c.visibility = 'public'")
    elif visibility in config.VISIBILITIES:
        where.append("c.visibility = ?")
        args.append(visibility)
    if admin and favorite:
        where.append("c.favorite = 1")
    if game == "none":
        where.append("c.game_id IS NULL")
    elif game.isdigit():
        where.append("c.game_id = ?")
        args.append(int(game))
    for word in q.split()[:8]:
        where.append("(c.title LIKE ? OR g.name LIKE ? OR c.filename LIKE ?)")
        args += [f"%{word}%"] * 3
    clause = " WHERE " + " AND ".join(where)
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    order = SORTS.get(sort) or SORTS[settings.get("default_sort")]
    with db.connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM clips c LEFT JOIN games g ON g.id = c.game_id" + clause, args
        ).fetchone()[0]
        rows = conn.execute(CLIP_SELECT + clause + f" ORDER BY {order} LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    return {"total": total, "clips": [clip_json(r, admin) for r in rows]}


@app.get("/api/clips/{clip_id}")
def clip_detail(clip_id: str, request: Request):
    return clip_json(get_clip(clip_id, request), is_admin(request))


def _appid(value) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        appid = int(value)
    except (TypeError, ValueError):
        raise HTTPException(400, "Steam app ID must be a number")
    if appid <= 0:
        raise HTTPException(400, "Steam app ID must be a positive number")
    return appid


def _set_game_steam(conn, game_id: int, appid: int | None, steam_name: str | None = None) -> None:
    """Pin a game to a Steam app (or to none) by hand. Metadata and artwork
    follow the new match; call `background(library.refresh_game, id, "", True)`
    after the transaction commits."""
    conn.execute(
        "UPDATE games SET steam_appid = ?, steam_name = ?, lookup_status = 'manual', description = NULL, "
        "release_date = NULL, developer = NULL, genres = NULL WHERE id = ?",
        (appid, steam_name, game_id),
    )


def _apply_clip_patch(conn, clip_id: str, body: dict) -> int | None:
    """Apply title/visibility/favorite/game changes. Returns a game ID whose
    Steam match changed (so the caller can refresh it), if any."""
    sets, args, rematched = [], [], None
    if "title" in body:
        title = " ".join(str(body["title"]).split())[:200]
        if not title:
            raise HTTPException(400, "Title can't be empty")
        sets.append("title = ?"); args.append(title)
    if "visibility" in body:
        if body["visibility"] not in config.VISIBILITIES:
            raise HTTPException(400, "Unknown visibility")
        sets.append("visibility = ?"); args.append(body["visibility"])
    if "favorite" in body:
        sets.append("favorite = ?"); args.append(int(bool(body["favorite"])))
    if "game" in body:
        name = " ".join(str(body["game"] or "").split())[:120]
        game_id = db.get_or_create_game(conn, name) if name else None
        sets += ["game_id = ?", "game_locked = 1"]; args.append(game_id)
        if game_id and "steam_appid" in body:
            appid = _appid(body["steam_appid"])
            current = conn.execute("SELECT steam_appid FROM games WHERE id = ?", (game_id,)).fetchone()[0]
            if appid != current:
                _set_game_steam(conn, game_id, appid, body.get("steam_name"))
                rematched = game_id
    if sets:
        conn.execute(f"UPDATE clips SET {', '.join(sets)} WHERE id = ?", [*args, clip_id])
    return rematched


def _prune(conn) -> None:
    for gid in db.prune_empty_games(conn):
        library.remove_art_files(gid)


def _after_rematch(game_id: int | None, wait: bool = False) -> None:
    """Load details and artwork for a game whose Steam match just changed."""
    if game_id is None:
        return
    with db.connect() as conn:
        row = conn.execute("SELECT steam_appid FROM games WHERE id = ?", (game_id,)).fetchone()
    if row and row["steam_appid"]:
        if wait:
            library.refresh_game(game_id, "", True)
        else:
            background(library.refresh_game, game_id, "", True)
    elif row:
        library.clear_art(game_id)


@app.patch("/api/clips/{clip_id}")
def update_clip(clip_id: str, request: Request, body: dict = Body(...)):
    require_admin(request)
    get_clip(clip_id, request)
    with db.connect() as conn:
        rematched = _apply_clip_patch(conn, clip_id, body)
        _prune(conn)
    _after_rematch(rematched)
    return clip_json(get_clip(clip_id, request), True)


@app.post("/api/clips/bulk")
def bulk_update(request: Request, body: dict = Body(...)):
    """Apply the same change (visibility, favorite, game) to many clips."""
    require_admin(request)
    ids = [str(i) for i in body.get("ids", [])][:1000]
    patch = {k: body[k] for k in ("visibility", "favorite", "game", "steam_appid", "steam_name") if k in body}
    if not ids or not patch:
        raise HTTPException(400, "Nothing to change")
    rematched = None
    with db.connect() as conn:
        for clip_id in ids:
            rematched = _apply_clip_patch(conn, clip_id, patch) or rematched
        _prune(conn)
    _after_rematch(rematched)
    return {"updated": len(ids)}


def _delete_clips(ids: list[str], delete_file: bool) -> int:
    """Remove clips from the library. With `delete_file`, the video file is
    deleted too; otherwise it stays on disk and is not imported again."""
    with db.connect() as conn:
        marks = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT id, path FROM clips WHERE missing = 0 AND id IN ({marks})", ids).fetchall()
    if delete_file:
        if not os.access(config.CLIPS_DIR, os.W_OK):
            raise HTTPException(409, "The clips folder is read-only, so files can't be deleted from here. "
                                     "Remove ':ro' from the clips volume in your compose file to allow it.")
        for row in rows:
            path = config.CLIPS_DIR / row["path"]
            if config.CLIPS_DIR not in path.resolve().parents:
                raise HTTPException(400, "Clip is outside the clips folder")
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise HTTPException(409, f"Couldn't delete {row['path']}: {exc.strerror or exc}")
            (config.THUMBS_DIR / f"{row['id']}.jpg").unlink(missing_ok=True)
            (config.MEDIA_DIR / f"{row['id']}.mp4").unlink(missing_ok=True)
            with db.connect() as conn:
                conn.execute("DELETE FROM clips WHERE id = ?", (row["id"],))
            log.info("Deleted clip file %s", row["path"])
    else:
        with db.connect() as conn:
            conn.executemany("UPDATE clips SET missing = 2 WHERE id = ?", [(r["id"],) for r in rows])
    with db.connect() as conn:
        _prune(conn)
    return len(rows)


@app.post("/api/clips/delete")
def delete_clips(request: Request, body: dict = Body(...)):
    require_admin(request)
    ids = [str(i) for i in body.get("ids", [])][:1000]
    if not ids:
        raise HTTPException(400, "Nothing to delete")
    return {"deleted": _delete_clips(ids, bool(body.get("file")))}


@app.post("/api/clips/{clip_id}/thumbnail")
def set_thumbnail(clip_id: str, request: Request, body: dict = Body(...)):
    """Use the frame at `time` seconds as the thumbnail, or reset with time=null."""
    require_admin(request)
    row = get_clip(clip_id, request)
    at = body.get("time")
    if at is not None:
        try:
            at = float(at)
        except (TypeError, ValueError):
            raise HTTPException(400, "time must be a number")
    if not media.make_thumbnail(config.CLIPS_DIR / row["path"], config.THUMBS_DIR / f"{row['id']}.jpg",
                                row["duration"] or 0, at):
        raise HTTPException(500, "Couldn't grab that frame")
    with db.connect() as conn:
        conn.execute("UPDATE clips SET thumb_v = thumb_v + 1, thumb_custom = ? WHERE id = ?", (int(at is not None), clip_id))
    return clip_json(get_clip(clip_id, request), True)


@app.post("/api/clips/{clip_id}/view")
def count_view(clip_id: str, request: Request):
    get_clip(clip_id, request)
    if not is_admin(request):
        with db.connect() as conn:
            conn.execute("UPDATE clips SET views = views + 1 WHERE id = ?", (clip_id,))
    return {"ok": True}


# ----------------------------------------------------------------- games ----

def game_json(row, clips: int | None = None, detail: bool = False) -> dict:
    v = row["art_v"]
    out = {"id": row["id"], "name": row["name"], "steam_appid": row["steam_appid"], "steam_name": row["steam_name"],
           "cover": f"/covers/{row['id']}.jpg?v={v}" if row["has_cover"] else None,
           "hero": f"/covers/{row['id']}-hero.jpg?v={v}" if row["has_hero"] else None}
    if clips is not None:
        out["clips"] = clips
    if detail:
        out.update(description=row["description"] or "", release_date=row["release_date"] or "",
                   developer=row["developer"] or "", genres=row["genres"] or "",
                   art_locked=bool(row["art_locked"]), lookup_status=row["lookup_status"])
    return out


@app.get("/api/games")
def list_games(request: Request):
    vis = "" if is_admin(request) else " AND c.visibility = 'public'"
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT g.*, COUNT(c.id) AS clips, MAX(c.recorded_at) AS latest "
            f"FROM games g JOIN clips c ON c.game_id = g.id AND c.missing = 0{vis} "
            "GROUP BY g.id ORDER BY g.name COLLATE NOCASE"
        ).fetchall()
        none = conn.execute(f"SELECT COUNT(*) FROM clips c WHERE c.missing = 0 AND c.game_id IS NULL{vis}").fetchone()[0]
    out = [{**game_json(r, r["clips"], detail=True), "latest": r["latest"]} for r in rows]
    return {"games": out, "uncategorized": none, "total": none + sum(g["clips"] for g in out)}


def _game_row(game_id: int):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Game not found")
    return row


@app.patch("/api/games/{game_id}")
def update_game(game_id: int, request: Request, body: dict = Body(...)):
    """Rename a game (merging into an existing one of that name), fix its Steam
    match, or edit its details. Affects every clip filed under the game."""
    require_admin(request)
    _game_row(game_id)
    rematched = None
    with db.connect() as conn:
        target = game_id
        if "name" in body:
            name = " ".join(str(body["name"] or "").split())[:120]
            if not name:
                raise HTTPException(400, "Name can't be empty")
            other = conn.execute("SELECT id FROM games WHERE name = ? AND id != ?", (name, game_id)).fetchone()
            if other:
                target = other["id"]
                conn.execute("UPDATE clips SET game_id = ? WHERE game_id = ?", (target, game_id))
                conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
                library.remove_art_files(game_id)
            else:
                conn.execute("UPDATE games SET name = ? WHERE id = ?", (name, game_id))
        if "steam_appid" in body:
            appid = _appid(body["steam_appid"])
            current = conn.execute("SELECT steam_appid FROM games WHERE id = ?", (target,)).fetchone()[0]
            if appid != current:
                _set_game_steam(conn, target, appid, body.get("steam_name"))
                rematched = target
        for field, limit in (("description", 2000), ("release_date", 60), ("developer", 200), ("genres", 200)):
            if field in body:
                conn.execute(f"UPDATE games SET {field} = ? WHERE id = ?", (str(body[field] or "").strip()[:limit], target))
    _after_rematch(rematched, wait=bool(body.get("wait")))
    return game_json(_game_row(target), detail=True)


@app.post("/api/games/{game_id}/refresh")
def refresh_game(game_id: int, request: Request, body: dict = Body(default={})):
    """Re-download details from Steam; with reset_art, also replace hand-picked artwork."""
    require_admin(request)
    row = _game_row(game_id)
    if not row["steam_appid"]:
        raise HTTPException(400, "This game isn't matched to Steam yet")
    if not library.refresh_game(game_id, reset_art=bool(body.get("reset_art"))):
        raise HTTPException(502, "Couldn't reach Steam")
    return game_json(_game_row(game_id), detail=True)


@app.get("/api/games/{game_id}/art")
def art_choices(game_id: int, request: Request, source: str = "steam", slot: str = "cover", q: str = ""):
    """Artwork on offer for a game: from Steam (the matched app), or from
    SteamGridDB (found by Steam app ID, by name, or by the search text `q`)."""
    require_admin(request)
    row = _game_row(game_id)
    if source == "sgdb":
        _slot(slot)
        try:
            found = None
            if q.strip():
                found = (sgdb.search(q.strip()) or [None])[0]
            elif row["steam_appid"]:
                found = sgdb.game_for_steam(row["steam_appid"])
            if not found and not q.strip():
                found = games.best_match(row["name"], sgdb.search(row["name"]))
            art = sgdb.images(found["id"], slot) if found else []
        except sgdb.SgdbError as exc:
            raise HTTPException(502, str(exc))
        return {"art": art, "matched": found["name"] if found else None}
    if not row["steam_appid"]:
        return {"art": []}
    try:
        details = games.steam_details(row["steam_appid"])
    except Exception as exc:
        raise HTTPException(502, f"Couldn't reach Steam: {exc}")
    return {"art": details["art"] if details else []}


def _slot(slot: str) -> str:
    if slot not in library.SLOTS:
        raise HTTPException(404, "Unknown artwork slot")
    return slot


@app.post("/api/games/{game_id}/art/{slot}")
def set_art_from_url(game_id: int, slot: str, request: Request, body: dict = Body(...)):
    require_admin(request)
    _game_row(game_id)
    try:
        blob = games.download_image(str(body.get("url", "")).strip())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Couldn't download that image: {exc}")
    if not library.set_art(game_id, _slot(slot), blob, lock=True):
        raise HTTPException(400, "That address isn't an image")
    return game_json(_game_row(game_id), detail=True)


@app.put("/api/games/{game_id}/art/{slot}")
async def upload_art(game_id: int, slot: str, request: Request):
    require_admin(request)
    _slot(slot)
    blob = await request.body()
    if not blob or len(blob) > MAX_UPLOAD:
        raise HTTPException(400, "Image is empty or larger than 15 MB")

    def work():
        _game_row(game_id)
        if not library.set_art(game_id, slot, blob, lock=True):
            raise HTTPException(400, "That file isn't an image")
        return game_json(_game_row(game_id), detail=True)
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(work)


@app.delete("/api/games/{game_id}/art")
def reset_art(game_id: int, request: Request):
    """Drop hand-picked artwork and go back to Steam's (or none)."""
    require_admin(request)
    row = _game_row(game_id)
    library.clear_art(game_id)
    if row["steam_appid"]:
        library.refresh_game(game_id)
    return game_json(_game_row(game_id), detail=True)


@app.get("/api/steam/search")
def steam_search(request: Request, q: str):
    require_admin(request)
    q = q.strip()
    try:
        if q.isdigit():       # an app ID pasted from SteamDB or the store address
            details = games.steam_details(int(q))
            return {"results": [{"appid": int(q), "name": details["name"], "image": details["header"]}] if details else []}
        return {"results": games.steam_search(q)[:10]}
    except Exception as exc:
        raise HTTPException(502, f"Couldn't reach Steam: {exc}")


# ----------------------------------------------------------------- media ----

@app.get("/v/{clip_id}")
def video(clip_id: str, request: Request, download: bool = False):
    row = get_clip(clip_id.rsplit(".", 1)[0], request)
    if download and not settings.get("allow_download") and not is_admin(request):
        raise HTTPException(403, "Downloads are turned off")
    original = config.CLIPS_DIR / row["path"]
    path = config.MEDIA_DIR / f"{row['id']}.mp4" if row["merged_audio"] else original
    if not path.is_file():
        path = original
    if not path.is_file() or config.CLIPS_DIR not in original.resolve().parents:
        raise HTTPException(404, "Clip file not found")
    kwargs = {"filename": row["filename"]} if download else {}
    return FileResponse(path, media_type=MIME.get(path.suffix.lower(), "video/mp4"),
                        headers={"Cache-Control": "private, max-age=3600"}, **kwargs)


@app.get("/t/{clip_id}.jpg")
def thumbnail(clip_id: str, request: Request):
    row = get_clip(clip_id, request)
    path = config.THUMBS_DIR / f"{row['id']}.jpg"
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/covers/{name}.jpg")
def cover(name: str):
    if not re.fullmatch(r"\d+(-hero)?", name):
        raise HTTPException(404)
    path = config.COVERS_DIR / f"{name}.jpg"
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


# ----------------------------------------------------------------- pages ----

def base_url(request: Request) -> str:
    return settings.get("base_url") or str(request.base_url).rstrip("/")


def _ink(color: str) -> str:
    """Readable text colour (dark or light) for a button in the accent colour."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#14100e" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#ffffff"


def render(name: str, status: int = 200, **values) -> HTMLResponse:
    page = (STATIC / name).read_text(encoding="utf-8")
    accent = settings.get("accent")
    values.setdefault("site_name", settings.get("site_name"))
    values.update(accent=accent, accent_ink=_ink(accent))

    def sub(m):  # single pass, so values can never be re-interpreted as placeholders
        key = m.group(1)
        if key not in values:
            return m.group(0)
        value = str(values[key])
        return value if key.endswith("_raw") else html.escape(value, quote=True)

    page = re.sub(r"\{\{(\w+)\}\}", sub, page)
    return HTMLResponse(page, status_code=status, headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def index():
    return render("index.html")


@app.get("/settings", response_class=HTMLResponse)
def settings_page():
    return render("settings.html")


@app.get("/w/{clip_id}", response_class=HTMLResponse)
def watch(clip_id: str, request: Request):
    try:
        row = get_clip(clip_id, request)
    except HTTPException:
        return render("notfound.html", status=404)
    admin = is_admin(request)
    base = base_url(request)
    site = settings.get("site_name")
    game = row["game_name"] or ""
    data = json.dumps(clip_json(row, admin)).replace("</", "<\\/")
    return render(
        "watch.html",
        title=row["title"],
        description=f"{game} clip on {site}" if game else f"Clip on {site}",
        page_url=f"{base}/w/{row['id']}",
        video_url=f"{base}/v/{row['id']}.mp4",
        thumb_url=f"{base}/t/{row['id']}.jpg?v={row['thumb_v']}",
        width=row["width"] or 1280,
        height=row["height"] or 720,
        robots="noindex" if row["visibility"] != "public" else "index",
        clip_json_raw=data,
        id_raw=row["id"],
        thumb_v=row["thumb_v"],
    )


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith(("/api/", "/v/", "/t/", "/covers/")):
        return JSONResponse({"detail": getattr(exc, "detail", "Not found")}, status_code=404)
    return render("notfound.html", status=404)
