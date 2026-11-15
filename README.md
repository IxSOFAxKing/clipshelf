# Clipshelf

A small self-hosted library for game clips. Point it at the folder your clips
are saved in and it imports them on its own, files them by game, and gives each
one a link you can share.

- **Folder watching**: new files are picked up within about 30 seconds, moved
  files keep their links, and deleted files drop out of the library. Your clips
  folder is mounted read-only; nothing in it is ever changed.
- **Games from file names**: `ARC-Raiders__2026-09-12__00-31-35.mp4` is filed
  under *ARC Raiders* and dated from the name. Each game is matched to Steam
  for artwork, a description, genres and a SteamDB link.
- **Game pages**: every game has a banner page with its artwork and details,
  and there is a grid of all your games.
- **Fix match and artwork**: search Steam by name or app ID to correct a match,
  then pick the cover and background from Steam's artwork and screenshots,
  paste an image address, or upload your own.
- **SteamGridDB artwork**: with a free API key, games Steam doesn't know
  (Fortnite, Valorant, ...) get artwork on their own, and the artwork picker
  gains a SteamGridDB tab with community covers and backgrounds.
- **Trimming**: cut a clip down in the browser by dragging start and end
  handles. The original file is never changed; the trimmed version is kept in
  the data folder, and the trim can be adjusted or removed later.
- **Highlights**: save a trimmed selection as a new clip with its own link,
  leaving the full clip as it is.
- **Installable**: add it to your phone's home screen or install it on a
  desktop as an app; on phones, sharing uses the system share sheet.
- **Deleting**: remove a clip from the library (the file stays on disk and can
  be brought back from Settings), or delete the file itself.
- **Sharing**: every clip is private, unlisted (anyone with the link) or public
  (listed on the home page). Share pages embed as playable video in Discord.
- **Clip tools**: rename, move between games, favorite, pick any frame as the
  thumbnail, and select many clips at once to change them together.
- **Settings in the browser**: site name, accent colour, sorting, scan
  interval, file-name rules with a live tester, sharing options, password, and
  library status with maintenance actions.
- **Mixed audio**: clips recorded with separate game and microphone tracks get
  a copy with the tracks mixed, since browsers only play the first one.

## Run it

The image is published at `ghcr.io/ixsofaxking/clipshelf:latest` and rebuilt on
every push to `main`. Copy `docker-compose.yml` (into a Komodo stack, Portainer,
or a folder on the server), set the path to your clips folder and a password,
then:

```bash
docker compose up -d
```

Open `http://<server>:8080` and sign in with the username and password from
the compose file (the username is `admin` unless you set `ADMIN_USERNAME`).

The library and settings are only available after signing in. Shared clip links
open without an account. If you would rather let visitors browse the clips you
mark Public, turn on Settings > Sharing > Public library.

Clips are private until you share them. The link button on a clip copies its
address and, if the clip was private, makes it unlisted.

### Getting clips from the gaming PC to the server

Either works:

- Share a folder from the server (SMB) and set it as the storage location in
  SteelSeries GG (Settings > Moments > Clip Settings > Storage Location).
- Keep saving locally and sync the Moments folder to the server with Syncthing.

Files that are still being copied are left alone until they stop growing.

## Settings

Open the gear icon in the header. Changes save as you make them and apply
straight away.

The environment variables below only set the starting values; once a setting is
changed in the browser, the browser's value wins.

| Variable | Default | What it does |
| --- | --- | --- |
| `ADMIN_USERNAME` | `admin` | Sign-in username. |
| `ADMIN_PASSWORD` | generated | Sign-in password. If empty, one is generated, printed in the logs and saved to `/data/admin_password.txt`. Changing this value also resets a username and password set in the browser. |
| `BASE_URL` | from the request | Public address, e.g. `https://clips.example.com`. Used in share links and embeds. |
| `SITE_NAME` | `Clipshelf` | Name shown in the header and in embeds. |
| `DEFAULT_VISIBILITY` | `private` | Visibility for newly imported clips: `private`, `unlisted` or `public`. |
| `SCAN_INTERVAL` | `30` | Seconds between checks of the clips folder. |
| `STEAM_LOOKUP` | `true` | Match game names to Steam. |
| `FILENAME_PATTERN` | none | Regular expression tried before the built-in ones. Needs a named group `game`; `date` and `time` are optional. |
| `FOLDER_AS_GAME` | `true` | Use the parent folder name as the game when the file name has none. |
| `MERGE_AUDIO_TRACKS` | `true` | Keep a mixed-audio copy of clips with more than one audio track (stored in `/data/media`). |
| `VIDEO_EXTENSIONS` | `mp4,mkv,mov,webm,m4v` | File types to import (environment only). |
| `TZ` | UTC | Time zone, used when a clip's date comes from the file rather than its name. |

### SteamGridDB

Sign in at steamgriddb.com, open Preferences > API, copy the key and paste it
under Settings > Artwork sources. It can also be supplied as the
`STEAMGRIDDB_API_KEY` environment variable.

### Trimming

Open a clip and choose Trim. Drag the handles (arrow keys nudge by a tenth of a
second), preview the selection, then save. Share links, embeds and downloads
all get the trimmed version.

"Save as new clip" keeps the clip you are looking at unchanged and adds the
selection as a separate clip (a highlight). Highlights live in the data folder,
so they stay available even if the recording they came from is later deleted.

By default the cut is exact, which re-encodes the trimmed part with ffmpeg and
can take a while for long clips on a small server. Settings > Library >
Trimming can be switched to Fast, which keeps the original video data but can
only start on a keyframe, so the start may shift by a second or two.

### Deleting clips

"Remove from library" always works: the clip disappears and its link stops
working, but the file is untouched. Removed clips can be restored from
Settings > Library status.

"Delete file" erases the video from the clips folder. It is only offered when
the folder is writable, so with the default read-only mount you first need to
change the volume in `docker-compose.yml` from

```yaml
- /path/to/your/clips:/clips:ro
```

to

```yaml
- /path/to/your/clips:/clips
```

The container runs as user 1000, which needs write permission on that folder.
If the folder syncs with your PC (Syncthing, for example), a file deleted here
may be deleted there too.

### How the game is worked out

1. `FILENAME_PATTERN`, if set.
2. Everything before the date in the file name. These all work:
   `Game__2026-11-10__21-15-32.mp4` (SteelSeries Moments; `ARC-Raiders__...` is read as
   *ARC Raiders*, and `DESKTOPCAPTURE` is not treated as a game), `Game 2026.11.10 - 21.15.32.01.DVR.mp4`,
   `Game_2026-11-10_21-15-32.mp4`, `Game 20261110_211532.mp4`.
3. The folder the file is in (`Halo/funny bounce.mp4` is filed under *Halo*).
4. Otherwise the clip is listed under "No game" until you set one.

If your recorder names files differently, set `FILENAME_PATTERN`. For example,
for `2026-11-10 21-15-32 - Game.mp4`:

```yaml
FILENAME_PATTERN: '^(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}-\d{2}-\d{2}) - (?P<game>.+)$'
```

### About SteamDB

SteamDB has no public API and asks not to be scraped, so names are matched
against Steam's own store search, which is the same catalogue with the same app
IDs. The app links to the SteamDB page for each matched game. Games that are
not on Steam (Fortnite, Valorant, League of Legends) are still grouped by name;
they get artwork from SteamGridDB if you add a key, or you can upload your own.

## Installing as an app

- **iPhone and iPad**: open the site in Safari, tap Share, then "Add to Home
  Screen".
- **Android and desktop (Chrome, Edge)**: Settings > Appearance > Install, or
  the browser menu's "Install app".

Android and desktop browsers only offer installing when the site is opened
over HTTPS, so this needs the reverse proxy setup below. The app icon follows
your accent colour.

## Putting it on the internet

Run it behind a reverse proxy with HTTPS (Caddy, Nginx Proxy Manager, Traefik,
a Cloudflare Tunnel) and set `BASE_URL` to the public address. Discord only
embeds video served over HTTPS. Only you can browse or change anything; visitors can open clips they have a
link to (and browse Public clips if you turn the public library on).

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
CLIPS_DIR=./clips DATA_DIR=./data ADMIN_PASSWORD=dev uvicorn app.main:app --reload
```

```bash
python -m pytest
```

Needs `ffmpeg` and `ffprobe` on the path.
