"""Game metadata and artwork."""
import logging
from pathlib import Path

from . import config, db, games, media

log = logging.getLogger("clipshelf.library")
SLOTS = {"cover": ("has_cover", 920), "hero": ("has_hero", 1920)}


def art_path(game_id: int, slot: str) -> Path:
    return config.COVERS_DIR / (f"{game_id}.jpg" if slot == "cover" else f"{game_id}-hero.jpg")


def set_art(game_id: int, slot: str, blob: bytes, lock: bool) -> bool:
    """Store an image as a game's cover or background. `lock` marks it as
    chosen by hand, so automatic refreshes leave it alone."""
    column, width = SLOTS[slot]
    if not media.image_to_jpeg(blob, art_path(game_id, slot), width):
        return False
    with db.connect() as conn:
        conn.execute(f"UPDATE games SET {column} = 1, art_v = art_v + 1, art_locked = MAX(art_locked, ?) WHERE id = ?",
                     (int(lock), game_id))
    return True


def remove_art_files(game_id: int) -> None:
    for slot in SLOTS:
        art_path(game_id, slot).unlink(missing_ok=True)


def clear_art(game_id: int, conn=None) -> None:
    remove_art_files(game_id)
    sql = "UPDATE games SET has_cover = 0, has_hero = 0, art_locked = 0, art_v = art_v + 1 WHERE id = ?"
    if conn is not None:
        conn.execute(sql, (game_id,))
    else:
        with db.connect() as c:
            c.execute(sql, (game_id,))


def _first_image(game_id: int, slot: str, urls) -> bool:
    for url in urls:
        if not url:
            continue
        try:
            if set_art(game_id, slot, games.download_image(url), lock=False):
                return True
        except Exception as exc:
            log.debug("artwork download failed (%s): %s", url, exc)
    return False


def refresh_game(game_id: int, fallback_url: str = "", reset_art: bool = False) -> bool:
    """Pull description, genres and artwork from Steam for a matched game.
    Hand-picked artwork is kept unless `reset_art` is set."""
    with db.connect() as conn:
        row = conn.execute("SELECT steam_appid, art_locked FROM games WHERE id = ?", (game_id,)).fetchone()
    if not row or not row["steam_appid"]:
        return False
    appid = row["steam_appid"]
    try:
        details = games.steam_details(appid)
    except Exception as exc:
        log.warning("Couldn't load Steam details for app %s: %s", appid, exc)
        details = None
    if details:
        with db.connect() as conn:
            conn.execute(
                "UPDATE games SET steam_name = ?, description = ?, release_date = ?, developer = ?, genres = ? "
                "WHERE id = ? AND steam_appid = ?",
                (details["name"], details["description"], details["release_date"], details["developer"],
                 details["genres"], game_id, appid),
            )
    if row["art_locked"] and not reset_art:
        return bool(details)
    if reset_art:
        clear_art(game_id)
    classic = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
    _first_image(game_id, "cover", [details and details["header"], classic, fallback_url])
    _first_image(game_id, "hero", details["hero"] if details else [])
    return bool(details)
