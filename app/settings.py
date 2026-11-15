"""Settings the admin can change in the browser.

Stored in the database; environment variables only supply the defaults, so an
existing docker-compose setup keeps working unchanged.
"""
import hashlib
import json
import re
import secrets

from . import config, db

SORTS = ("newest", "oldest", "views", "longest", "title")
DEFAULT_IGNORED = "DESKTOPCAPTURE, Desktop, Replay, Clip, Video, Recording, Moment, Moments, Capture, Screen Recording"


def _text(limit):
    def check(v):
        return " ".join(str(v).split())[:limit]
    return check


def _bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _int(lo, hi):
    def check(v):
        n = int(v)
        if not lo <= n <= hi:
            raise ValueError(f"must be between {lo} and {hi}")
        return n
    return check


def _choice(options):
    def check(v):
        if v not in options:
            raise ValueError(f"must be one of: {', '.join(options)}")
        return v
    return check


def _color(v):
    v = str(v).strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        raise ValueError("must be a colour like #ff7a45")
    return v.lower()


def _url(v):
    v = str(v).strip().rstrip("/")
    if v and not re.match(r"https?://[^\s/]+", v):
        raise ValueError("must start with http:// or https://")
    return v


def _pattern(v):
    v = str(v).strip()
    if v:
        try:
            groups = re.compile(v).groupindex
        except re.error as exc:
            raise ValueError(f"not a valid pattern: {exc}")
        if "game" not in groups and "date" not in groups:
            raise ValueError("needs a named group, e.g. (?P<game>.+)")
    return v


# key -> (validator, default)
SPEC = {
    "site_name": (_text(60), config.SITE_NAME),
    "accent": (_color, "#ff7a45"),
    "default_sort": (_choice(SORTS), "newest"),
    "group_by_month": (_bool, True),
    "hover_preview": (_bool, True),
    "base_url": (_url, config.BASE_URL),
    "default_visibility": (_choice(config.VISIBILITIES), config.DEFAULT_VISIBILITY),
    "allow_download": (_bool, True),
    "show_views": (_bool, True),
    "scan_interval": (_int(5, 86400), config.SCAN_INTERVAL),
    "steam_lookup": (_bool, config.STEAM_LOOKUP),
    "filename_pattern": (_pattern, config.FILENAME_PATTERN),
    "folder_as_game": (_bool, config.FOLDER_AS_GAME),
    "ignored_names": (_text(1000), DEFAULT_IGNORED),
    "merge_audio_tracks": (_bool, config.MERGE_AUDIO_TRACKS),
    "trim_mode": (_choice(("exact", "fast")), "exact"),
}
# Sent to every visitor (the rest is admin-only).
PUBLIC = ("site_name", "default_sort", "group_by_month", "hover_preview", "allow_download", "show_views")

_values: dict = {}
_internal: dict = {}   # password hash etc.; never sent to the browser


def load() -> None:
    _values.clear()
    _internal.clear()
    with db.connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for row in rows:
        try:
            value = json.loads(row["value"])
        except ValueError:
            continue
        if row["key"] in SPEC:
            try:
                _values[row["key"]] = SPEC[row["key"]][0](value)
            except (ValueError, TypeError):
                pass
        else:
            _internal[row["key"]] = value
    # Changing ADMIN_PASSWORD in the environment resets a password set in the browser.
    if _internal.get("password_hash") and _internal.get("password_env") != _fingerprint(config.ADMIN_PASSWORD):
        _store({"password_hash": None, "password_env": None})


def get(key: str):
    return _values.get(key, SPEC[key][1])


def all_values() -> dict:
    return {key: get(key) for key in SPEC}


def public_values() -> dict:
    return {key: get(key) for key in PUBLIC}


def _store(pairs: dict) -> None:
    with db.connect() as conn:
        for key, value in pairs.items():
            if value is None:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))
    for key, value in pairs.items():
        target = _values if key in SPEC else _internal
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value


def update(changes: dict) -> dict:
    """Validate and save. Raises ValueError("<label>: <problem>") on bad input."""
    clean = {}
    for key, value in changes.items():
        if key not in SPEC:
            continue
        try:
            clean[key] = SPEC[key][0](value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} {exc}")
    _store(clean)
    return all_values()


def reset(keys) -> dict:
    _store({key: None for key in keys if key in SPEC})
    return all_values()


def sgdb_key() -> str:
    return _internal.get("steamgriddb_api_key") or config.STEAMGRIDDB_API_KEY


def set_sgdb_key(key: str) -> None:
    _store({"steamgriddb_api_key": key.strip() or None})


def ignored_names() -> set[str]:
    return {n.strip().lower() for n in get("ignored_names").split(",") if n.strip()}


# ------------------------------------------------------------- password ----

def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def check_password(password: str) -> bool:
    stored = _internal.get("password_hash")
    if stored:
        salt, _, digest = stored.partition("$")
        return secrets.compare_digest(_hash(password, salt), digest)
    return secrets.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode())


def set_password(password: str) -> None:
    salt = secrets.token_hex(16)
    _store({"password_hash": f"{salt}${_hash(password, salt)}", "password_env": _fingerprint(config.ADMIN_PASSWORD)})


def session_material() -> bytes:
    """Mixed into session signatures so changing the password signs everyone out."""
    return (_internal.get("password_hash") or config.ADMIN_PASSWORD).encode()
