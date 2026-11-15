"""SteamGridDB: community artwork, including games that aren't on Steam.

Needs a free API key from the user's SteamGridDB account preferences.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from . import settings

BASE = "https://www.steamgriddb.com/api/v2"
FILTERS = "types=static&nsfw=false&humor=false"


class SgdbError(Exception):
    """A problem worth showing to the admin (bad key, service down)."""


def _call(path: str, key: str | None = None):
    key = key or settings.sgdb_key()
    if not key:
        raise SgdbError("Add a SteamGridDB API key in Settings first")
    req = urllib.request.Request(BASE + path, headers={
        "Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0 (compatible; clip-library)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SgdbError("SteamGridDB didn't accept the API key")
        if exc.code == 404:
            return None
        raise SgdbError(f"SteamGridDB returned an error ({exc.code})")
    except (OSError, ValueError) as exc:
        raise SgdbError(f"Couldn't reach SteamGridDB: {exc}")
    return body.get("data") if body.get("success") else None


def check_key(key: str) -> None:
    """Raises SgdbError if the key is rejected."""
    _call("/search/autocomplete/portal", key)


def search(term: str) -> list[dict]:
    data = _call("/search/autocomplete/" + urllib.parse.quote(term, safe="")) or []
    return [{"id": g["id"], "name": g.get("name", "")} for g in data if "id" in g]


def game_for_steam(appid: int) -> dict | None:
    data = _call(f"/games/steam/{int(appid)}")
    return {"id": data["id"], "name": data.get("name", "")} if data and "id" in data else None


def images(game_id: int, slot: str) -> list[dict]:
    """Artwork for a SteamGridDB game: wide grids for covers, heroes for backgrounds."""
    if slot == "cover":
        path = f"/grids/game/{int(game_id)}?dimensions=460x215,920x430&{FILTERS}"
    else:
        path = f"/heroes/game/{int(game_id)}?{FILTERS}"
    out = []
    for item in _call(path) or []:
        if not item.get("url"):
            continue
        author = (item.get("author") or {}).get("name")
        out.append({"label": f"by {author}" if author else "SteamGridDB",
                    "url": item["url"], "thumb": item.get("thumb") or item["url"]})
    return out[:40]
