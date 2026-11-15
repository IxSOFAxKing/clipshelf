"""Clipshelf web app: JSON API, share pages and media delivery."""
import hashlib
import hmac
import html
import json
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, games, media
from .scanner import refresh_cover, scanner

log = logging.getLogger("clipshelf")
STATIC = Path(__file__).parent / "static"
COOKIE = "clipshelf_session"
MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/mp4",
        ".webm": "video/webm", ".mkv": "video/x-matroska"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config.init()
    db.init()
    if config.PASSWORD_WAS_GENERATED:
        log.warning("ADMIN_PASSWORD is not set. Generated admin password: %s "
                    "(saved in %s/admin_password.txt)", config.ADMIN_PASSWORD, config.DATA_DIR)
    log.info("Watching %s (every %ss); data in %s", config.CLIPS_DIR, config.SCAN_INTERVAL, config.DATA_DIR)
    scanner.start()
    yield


app = FastAPI(title="Clipshelf", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


# ------------------------------------------------------------------ auth ----

def _sign(expires: int) -> str:
    return hmac.new(config.SECRET_KEY, str(expires).encode(), hashlib.sha256).hexdigest()


def is_admin(request: Request) -> bool:
    token = request.cookies.get(COOKIE, "")
    expires, _, sig = token.partition(".")
    if not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(int(expires)))


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(401, "Sign in required")


_failed_logins: list[float] = []


@app.post("/api/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    now = time.time()
    _failed_logins[:] = [t for t in _failed_logins if now - t < 300]
    if len(_failed_logins) >= 10:
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    password = str(body.get("password", ""))
    if not hmac.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode()):
        _failed_logins.append(now)
        time.sleep(0.5)
        raise HTTPException(401, "Wrong password")
    expires = int(now) + config.SESSION_DAYS * 86400
    response.set_cookie(COOKIE, f"{expires}.{_sign(expires)}", max_age=config.SESSION_DAYS * 86400,
                        httponly=True, samesite="lax", secure=config.SECURE_COOKIES)
    return {"admin": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"admin": False}


@app.get("/api/me")
def me(request: Request):
    admin = is_admin(request)
    out = {"admin": admin, "site_name": config.SITE_NAME}
    if admin:
        out["scanner"] = scanner.status
    return out


# ----------------------------------------------------------------- clips ----

CLIP_SELECT = """
SELECT c.*, g.name AS game_name, g.steam_appid, g.steam_name, g.has_cover
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
        "views": row["views"],
        "web_playable": (row["vcodec"] or "") in media.WEB_CODECS,
        "game": None,
    }
    if row["game_id"]:
        out["game"] = {"id": row["game_id"], "name": row["game_name"], "steam_appid": row["steam_appid"],
                       "steam_name": row["steam_name"], "has_cover": bool(row["has_cover"])}
    if admin:
        out.update(favorite=bool(row["favorite"]), filename=row["path"], size=row["size"],
                   vcodec=row["vcodec"], audio_tracks=row["audio_tracks"])
    return out


def get_clip(clip_id: str, request: Request):
    """Fetch a clip the requester is allowed to see, else 404."""
    with db.connect() as conn:
        row = conn.execute(CLIP_SELECT + " WHERE c.id = ? AND c.missing = 0", (clip_id,)).fetchone()
    if not row or (row["visibility"] == "private" and not is_admin(request)):
        raise HTTPException(404, "Clip not found")
    return row


@app.get("/api/clips")
def list_clips(request: Request, game: str = "", q: str = "", sort: str = "newest",
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
    with db.connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM clips c LEFT JOIN games g ON g.id = c.game_id" + clause, args
        ).fetchone()[0]
        rows = conn.execute(
            CLIP_SELECT + clause + f" ORDER BY {SORTS.get(sort, SORTS['newest'])} LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
    return {"total": total, "clips": [clip_json(r, admin) for r in rows]}


@app.get("/api/games")
def list_games(request: Request):
    admin = is_admin(request)
    vis = "" if admin else " AND c.visibility = 'public'"
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT g.id, g.name, g.steam_appid, g.steam_name, g.has_cover, g.lookup_status, COUNT(c.id) AS clips "
            f"FROM games g JOIN clips c ON c.game_id = g.id AND c.missing = 0{vis} "
            "GROUP BY g.id ORDER BY g.name COLLATE NOCASE"
        ).fetchall()
        none = conn.execute(f"SELECT COUNT(*) FROM clips c WHERE c.missing = 0 AND c.game_id IS NULL{vis}").fetchone()[0]
    out = [{"id": r["id"], "name": r["name"], "steam_appid": r["steam_appid"], "steam_name": r["steam_name"],
            "has_cover": bool(r["has_cover"]), "clips": r["clips"]} for r in rows]
    return {"games": out, "uncategorized": none, "total": none + sum(g["clips"] for g in out)}


@app.get("/api/clips/{clip_id}")
def clip_detail(clip_id: str, request: Request):
    return clip_json(get_clip(clip_id, request), is_admin(request))


def _set_game_steam(conn, game_id: int, appid: int | None, steam_name: str | None = None) -> None:
    """Pin a game to a Steam app (or to none) by hand and refresh its cover."""
    conn.execute(
        "UPDATE games SET steam_appid = ?, steam_name = ?, lookup_status = 'manual', has_cover = 0 WHERE id = ?",
        (appid, steam_name, game_id),
    )
    if appid:
        def work():
            name = steam_name or games.steam_app_name(appid)
            if name and not steam_name:
                with db.connect() as c:
                    c.execute("UPDATE games SET steam_name = ? WHERE id = ? AND steam_appid = ?", (name, game_id, appid))
            refresh_cover(game_id, appid)
        threading.Thread(target=work, daemon=True).start()
    else:
        (config.COVERS_DIR / f"{game_id}.jpg").unlink(missing_ok=True)


def _appid(value) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        appid = int(value)
    except (TypeError, ValueError):
        raise HTTPException(400, "steam_appid must be a number")
    if appid <= 0:
        raise HTTPException(400, "steam_appid must be a positive number")
    return appid


@app.patch("/api/clips/{clip_id}")
def update_clip(clip_id: str, request: Request, body: dict = Body(...)):
    require_admin(request)
    get_clip(clip_id, request)
    sets, args = [], []
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
    with db.connect() as conn:
        if "game" in body:
            name = " ".join(str(body["game"] or "").split())[:120]
            game_id = db.get_or_create_game(conn, name) if name else None
            sets += ["game_id = ?", "game_locked = 1"]; args.append(game_id)
            if game_id and "steam_appid" in body:
                appid = _appid(body["steam_appid"])
                current = conn.execute("SELECT steam_appid FROM games WHERE id = ?", (game_id,)).fetchone()[0]
                if appid != current:
                    _set_game_steam(conn, game_id, appid, body.get("steam_name"))
        if sets:
            conn.execute(f"UPDATE clips SET {', '.join(sets)} WHERE id = ?", [*args, clip_id])
        for gid in db.prune_empty_games(conn):
            (config.COVERS_DIR / f"{gid}.jpg").unlink(missing_ok=True)
    return clip_json(get_clip(clip_id, request), True)


@app.patch("/api/games/{game_id}")
def update_game(game_id: int, request: Request, body: dict = Body(...)):
    """Rename a game (merging into an existing one of that name) and/or fix
    its Steam match. Affects every clip filed under the game."""
    require_admin(request)
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM games WHERE id = ?", (game_id,)).fetchone():
            raise HTTPException(404, "Game not found")
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
                (config.COVERS_DIR / f"{game_id}.jpg").unlink(missing_ok=True)
            else:
                conn.execute("UPDATE games SET name = ? WHERE id = ?", (name, game_id))
        if "steam_appid" in body:
            appid = _appid(body["steam_appid"])
            current = conn.execute("SELECT steam_appid FROM games WHERE id = ?", (target,)).fetchone()[0]
            if appid != current or appid is None:
                _set_game_steam(conn, target, appid, body.get("steam_name"))
    return {"id": target}


@app.post("/api/clips/{clip_id}/view")
def count_view(clip_id: str, request: Request):
    get_clip(clip_id, request)
    if not is_admin(request):
        with db.connect() as conn:
            conn.execute("UPDATE clips SET views = views + 1 WHERE id = ?", (clip_id,))
    return {"ok": True}


@app.get("/api/steam/search")
def steam_search(request: Request, q: str):
    require_admin(request)
    try:
        return {"results": games.steam_search(q.strip())[:8]}
    except Exception as exc:
        raise HTTPException(502, f"Couldn't reach Steam: {exc}")


@app.post("/api/rescan")
def rescan(request: Request):
    require_admin(request)
    scanner.trigger()
    return {"ok": True}


# ----------------------------------------------------------------- media ----

@app.get("/v/{clip_id}")
def video(clip_id: str, request: Request, download: bool = False):
    row = get_clip(clip_id.rsplit(".", 1)[0], request)
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


@app.get("/covers/{game_id}.jpg")
def cover(game_id: int):
    path = config.COVERS_DIR / f"{game_id}.jpg"
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})


# ----------------------------------------------------------------- pages ----

def base_url(request: Request) -> str:
    return config.BASE_URL or str(request.base_url).rstrip("/")


def render(name: str, status: int = 200, **values) -> HTMLResponse:
    page = (STATIC / name).read_text(encoding="utf-8")
    values.setdefault("site_name", config.SITE_NAME)
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


@app.get("/w/{clip_id}", response_class=HTMLResponse)
def watch(clip_id: str, request: Request):
    try:
        row = get_clip(clip_id, request)
    except HTTPException:
        return render("notfound.html", status=404)
    admin = is_admin(request)
    base = base_url(request)
    game = row["game_name"] or ""
    data = json.dumps(clip_json(row, admin)).replace("</", "<\\/")
    return render(
        "watch.html",
        title=row["title"],
        description=f"{game} clip on {config.SITE_NAME}" if game else f"Clip on {config.SITE_NAME}",
        page_url=f"{base}/w/{row['id']}",
        video_url=f"{base}/v/{row['id']}.mp4",
        thumb_url=f"{base}/t/{row['id']}.jpg",
        width=row["width"] or 1280,
        height=row["height"] or 720,
        robots="noindex" if row["visibility"] != "public" else "index",
        clip_json_raw=data,
        id_raw=row["id"],
    )


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/") or request.url.path.startswith(("/v/", "/t/", "/covers/")):
        return JSONResponse({"detail": getattr(exc, "detail", "Not found")}, status_code=404)
    return render("notfound.html", status=404)
