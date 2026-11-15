"""Work out which game a clip belongs to, and match game names to Steam.

SteamDB has no public API and asks not to be scraped, so matching uses the
official Steam store endpoints (the same catalogue and app IDs); the UI links
out to SteamDB by app ID.
"""
import difflib
import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import config

log = logging.getLogger("clipshelf.games")

_DATE = r"(?P<date>(?:19|20)\d{2}[-._]\d{2}[-._]\d{2})"
_TIME = r"(?P<time>\d{2}[-._:h]\d{2}(?:[-._:m]\d{2})?)"
_SEP = r"[\s_\-]+"
BUILTIN_PATTERNS = [
    # "Game__2024-03-10__21-15-32"        (SteelSeries Moments style)
    # "Game 2024.03.10 - 21.15.32.01.DVR" (NVIDIA ShadowPlay)
    # "Game_2024-03-10_21-15-32", "Game 2024-03-10 21-15-32" (Medal, OBS, ...)
    re.compile(rf"^(?P<game>.+?){_SEP}{_DATE}(?:[\sT_\-]+{_TIME})?"),
    # "Game_20240310_211532" / "Game 20240310211532"
    re.compile(rf"^(?P<game>.+?){_SEP}(?P<date>(?:19|20)\d{{6}})[_\-\s]?(?P<time>\d{{6}})"),
    # No game, just a timestamp: "2024-03-10 21-15-32", "Replay 2024-03-10 ..."
    re.compile(rf"^{_DATE}(?:[\sT_\-]+{_TIME})?"),
]
# Words recorders put where the game name would be.
_NOT_GAMES = {"desktopcapture", "desktop capture", "replay", "clip", "video", "recording", "desktop", "moment", "moments", "capture", "screen recording"}


def _parse_datetime(date: str | None, time: str | None) -> datetime | None:
    if not date:
        return None
    d = re.sub(r"\D", "", date)
    t = (re.sub(r"\D", "", time or "") + "000000")[:6]
    try:
        return datetime.strptime(d + t, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _clean_name(raw: str) -> str:
    name = re.sub(r"[_\s]+", " ", raw).strip(" -_.")
    # SteelSeries Moments writes spaces as hyphens ("ARC-Raiders", "Ready-or-Not").
    if " " not in name and "-" in name:
        name = name.replace("-", " ")
    return name


def parse_clip_path(rel_path: str) -> tuple[str | None, datetime | None]:
    """Return (game name or None, recording time or None) for a clip path."""
    p = PurePosixPath(rel_path.replace("\\", "/"))
    stem = p.stem
    game: str | None = None
    when: datetime | None = None

    patterns = list(BUILTIN_PATTERNS)
    if config.FILENAME_PATTERN:
        try:
            patterns.insert(0, re.compile(config.FILENAME_PATTERN))
        except re.error as exc:
            log.warning("Ignoring invalid FILENAME_PATTERN: %s", exc)

    for pat in patterns:
        m = pat.search(stem)
        if not m:
            continue
        groups = m.groupdict()
        when = _parse_datetime(groups.get("date"), groups.get("time"))
        if groups.get("game"):
            game = _clean_name(groups["game"])
        break

    if game and game.lower() in _NOT_GAMES:
        game = None
    if not game and config.FOLDER_AS_GAME and len(p.parts) > 1:
        game = _clean_name(p.parts[-2])
    return (game or None), when


def default_title(rel_path: str, game: str | None, when: datetime | None) -> str:
    if game and when:
        trimmed = " (trimmed)" if re.search(r"[_\- ]trim", PurePosixPath(rel_path).stem, re.I) else ""
        return f"{game} · {when.strftime('%b %-d, %Y %-I:%M %p')}{trimmed}"
    return _clean_name(PurePosixPath(rel_path).stem) or "Untitled clip"


# ---------------------------------------------------------------- Steam ----

_UA = {"User-Agent": "Mozilla/5.0 (compatible; clip-library)"}


def _get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def norm(name: str) -> str:
    name = name.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", name)


def steam_search(term: str) -> list[dict]:
    """Search the Steam store. Returns [{appid, name, image}]."""
    url = "https://store.steampowered.com/api/storesearch/?" + urllib.parse.urlencode(
        {"term": term, "l": "english", "cc": "US"}
    )
    data = json.loads(_get(url))
    out = []
    for item in data.get("items", []):
        if item.get("type", "app") != "app" or "id" not in item:
            continue
        out.append({"appid": int(item["id"]), "name": item.get("name", ""), "image": item.get("tiny_image", "")})
    return out


def best_match(name: str, results: list[dict]) -> dict | None:
    """Pick the search result that is confidently the same game, if any."""
    target = norm(name)
    if not target:
        return None
    best, best_score = None, 0.0
    for r in results:
        cand = norm(r["name"])
        score = 1.0 if cand == target else difflib.SequenceMatcher(None, target, cand).ratio()
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= 0.8 else None


def fetch_cover(appid: int, dest: Path, fallback_url: str = "") -> bool:
    """Download header art for a Steam app to `dest`. Returns success."""
    urls = []
    try:
        details = json.loads(
            _get(f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic")
        )
        header = (details.get(str(appid), {}).get("data") or {}).get("header_image")
        if header:
            urls.append(header)
    except Exception as exc:  # network / JSON problems fall through to guesses
        log.debug("appdetails failed for %s: %s", appid, exc)
    urls.append(f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg")
    if fallback_url:
        urls.append(fallback_url)
    for url in urls:
        try:
            blob = _get(url)
            if len(blob) > 1000:
                tmp = dest.with_suffix(".tmp")
                tmp.write_bytes(blob)
                tmp.replace(dest)
                return True
        except Exception as exc:
            log.debug("cover download failed (%s): %s", url, exc)
    return False


def steam_app_name(appid: int) -> str | None:
    try:
        details = json.loads(
            _get(f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic")
        )
        return (details.get(str(appid), {}).get("data") or {}).get("name")
    except Exception:
        return None
