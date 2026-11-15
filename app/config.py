"""Runtime configuration, read once from environment variables."""
import os
import secrets
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


CLIPS_DIR = Path(os.environ.get("CLIPS_DIR", "/clips")).resolve()
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
THUMBS_DIR = DATA_DIR / "thumbs"
COVERS_DIR = DATA_DIR / "covers"
MEDIA_DIR = DATA_DIR / "media"
ICONS_DIR = DATA_DIR / "icons"
DB_PATH = DATA_DIR / "clipshelf.db"

SITE_NAME = os.environ.get("SITE_NAME", "Clipshelf")
# Public URL of the site (e.g. https://clips.example.com). Used for share
# links and Discord/Open Graph embeds. If empty, derived from each request.
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

SCAN_INTERVAL = max(5, int(os.environ.get("SCAN_INTERVAL", "30")))
VIDEO_EXTENSIONS = tuple(
    "." + e.strip().lower().lstrip(".")
    for e in os.environ.get("VIDEO_EXTENSIONS", "mp4,mkv,mov,webm,m4v").split(",")
    if e.strip()
)

# private  = only the admin can see it
# unlisted = anyone with the link can watch
# public   = listed on the home page for everyone
VISIBILITIES = ("private", "unlisted", "public")
DEFAULT_VISIBILITY = os.environ.get("DEFAULT_VISIBILITY", "private").lower()
if DEFAULT_VISIBILITY not in VISIBILITIES:
    DEFAULT_VISIBILITY = "private"

STEAM_LOOKUP = _bool("STEAM_LOOKUP", True)
# Optional regex with a named group `game` (and optionally `date`, `time`)
# tried before the built-in filename patterns.
FILENAME_PATTERN = os.environ.get("FILENAME_PATTERN", "")
# Use the parent folder name as the game when the filename has none.
FOLDER_AS_GAME = _bool("FOLDER_AS_GAME", True)
# Clips with separate game/mic audio tracks only play their first track in a
# browser. When enabled, a copy with all tracks mixed is kept in DATA_DIR.
MERGE_AUDIO_TRACKS = _bool("MERGE_AUDIO_TRACKS", True)

# Optional key for extra artwork from steamgriddb.com (can also be set in the browser).
STEAMGRIDDB_API_KEY = os.environ.get("STEAMGRIDDB_API_KEY", "").strip()

SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))
SECURE_COOKIES = _bool("SECURE_COOKIES", BASE_URL.startswith("https://"))

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
PASSWORD_WAS_GENERATED = False
SECRET_KEY = b""


def init() -> None:
    """Create data directories and load (or create) persistent secrets."""
    global ADMIN_PASSWORD, PASSWORD_WAS_GENERATED, SECRET_KEY
    for d in (DATA_DIR, THUMBS_DIR, COVERS_DIR, MEDIA_DIR, ICONS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    key_file = DATA_DIR / "secret.key"
    if not key_file.exists():
        key_file.write_bytes(secrets.token_bytes(32))
        key_file.chmod(0o600)
    SECRET_KEY = key_file.read_bytes()

    if not ADMIN_PASSWORD:
        pw_file = DATA_DIR / "admin_password.txt"
        if not pw_file.exists():
            pw_file.write_text(secrets.token_urlsafe(12))
            pw_file.chmod(0o600)
        ADMIN_PASSWORD = pw_file.read_text().strip()
        PASSWORD_WAS_GENERATED = True
