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

from . import settings

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


def parse_clip_path(rel_path: str, pattern: str | None = None) -> tuple[str | None, datetime | None]:
    """Return (game name or None, recording time or None) for a clip path."""
    p = PurePosixPath(rel_path.replace("\\", "/"))
    stem = p.stem
    game: str | None = None
    when: datetime | None = None

    patterns = list(BUILTIN_PATTERNS)
    custom = settings.get("filename_pattern") if pattern is None else pattern
    if custom:
        try:
            patterns.insert(0, re.compile(custom))
        except re.error as exc:
            log.warning("Ignoring invalid file name pattern: %s", exc)

    for pat in patterns:
        m = pat.search(stem)
        if not m:
            continue
        groups = m.groupdict()
        when = _parse_datetime(groups.get("date"), groups.get("time"))
        if groups.get("game"):
            game = _clean_name(groups["game"])
        break

    if game and game.lower() in settings.ignored_names():
        game = None
    if not game and settings.get("folder_as_game") and len(p.parts) > 1:
        game = _clean_name(p.parts[-2])
    return (game or None), when


def default_title(rel_path: str, game: str | None, when: datetime | None) -> str:
    if game and when:
        trimmed = " (trimmed)" if re.search(r"[_\- ]trim", PurePosixPath(rel_path).stem, re.I) else ""
        return f"{game} · {when.strftime('%b %-d, %Y %-I:%M %p')}{trimmed}"
    stem = PurePosixPath(rel_path).stem
    if when:  # no game: keep whatever came before the date ("DESKTOPCAPTURE") readable
        lead = _clean_name(re.split(r"[\s_\-]*(?:19|20)\d{2}", stem)[0]) or "Clip"
        return f"{lead} · {when.strftime('%b %-d, %Y %-I:%M %p')}"
    return _clean_name(stem) or "Untitled clip"


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


def steam_details(appid: int) -> dict | None:
    """Store page details for an app: text metadata plus artwork URLs."""
    raw = json.loads(_get(f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english&cc=US"))
    data = (raw.get(str(appid)) or {}).get("data")
    if not data:
        return None
    header = data.get("header_image") or ""
    art = []

    def add(label, url, thumb=""):
        if url and url not in [a["url"] for a in art]:
            art.append({"label": label, "url": url, "thumb": thumb or url})

    def sibling(name):  # other artwork usually sits next to header.jpg
        return re.sub(r"header[^/?]*\.jpg", name, header) if "header" in header else ""

    add("Header", header)
    add("Capsule", sibling("capsule_616x353.jpg"))
    add("Library banner", sibling("library_hero.jpg"))
    add("Store background", data.get("background_raw") or data.get("background"))
    for n, shot in enumerate(data.get("screenshots") or [], 1):
        add(f"Screenshot {n}", shot.get("path_full"), shot.get("path_thumbnail"))
    return {
        "appid": appid,
        "name": data.get("name") or "",
        "description": re.sub(r"<[^>]+>", "", data.get("short_description") or "").strip(),
        "release_date": (data.get("release_date") or {}).get("date") or "",
        "developer": ", ".join(data.get("developers") or []),
        "genres": ", ".join(g.get("description", "") for g in data.get("genres") or []),
        "header": header,
        "hero": [a["url"] for a in art if a["label"] in ("Library banner", "Store background", "Screenshot 1")],
        "art": art,
    }


def download_image(url: str, limit: int = 15_000_000) -> bytes:
    if not re.match(r"https?://", url):
        raise ValueError("Image address must start with http:// or https://")
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        blob = resp.read(limit + 1)
    if len(blob) > limit:
        raise ValueError("Image is too large")
    return blob
