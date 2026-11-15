import json
import os
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def site():
    clips, data = Path(os.environ["CLIPS_DIR"]), Path(os.environ["DATA_DIR"])

    from fastapi.testclient import TestClient
    from app import games, settings
    from app.main import app
    from app.scanner import scanner

    jpeg = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=460x215", "-frames:v", "1",
                           "-f", "mjpeg", "-"], capture_output=True, check=True).stdout

    def fake_get(url, timeout=15):
        if "storesearch" in url:
            return json.dumps({"items": [{"type": "app", "id": 730, "name": "Counter-Strike 2", "tiny_image": "x"}]}).encode()
        if "appdetails" in url:
            appid = url.split("appids=")[1].split("&")[0]
            return json.dumps({appid: {"data": {
                "name": "Counter-Strike 2", "short_description": "A <b>tactical</b> shooter.",
                "header_image": "https://img.test/apps/730/header.jpg?t=1", "background_raw": "https://img.test/bg.jpg",
                "developers": ["Valve"], "genres": [{"description": "Action"}], "release_date": {"date": "Aug 21, 2012"},
                "screenshots": [{"path_thumbnail": "https://img.test/s1t.jpg", "path_full": "https://img.test/s1.jpg"}],
            }}}).encode()
        return jpeg
    games._get = fake_get
    games.download_image = lambda url, limit=0: jpeg
    games._get = fake_get

    def add_clip(name, age=600):
        path = clips / name
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10",
                        "-t", "2", "-pix_fmt", "yuv420p", str(path)], check=True)
        old = time.time() - age
        os.utime(path, (old, old))
        return path

    with TestClient(app) as client:
        settings.update({"public_library": True})   # most tests check what visitors can browse
        yield {"client": client, "clips": clips, "data": data, "scan": scanner.scan_once, "add": add_clip}


def login(client):
    # "secret123" once test_change_password has run
    assert any(client.post("/api/login", json={"username": name, "password": pw}).status_code == 200
               for name, pw in (("admin", "pw"), ("boss", "secret123")))


def test_import_and_visibility(site):
    c = site["client"]
    site["add"]("Counter-Strike 2__2026-11-10__21-15-32.mp4")
    site["scan"]()

    assert c.get("/api/clips").json()["total"] == 0          # private by default
    assert c.post("/api/login", json={"username": "admin", "password": "nope"}).status_code == 401
    assert c.post("/api/login", json={"username": "someone", "password": "pw"}).status_code == 401
    login(c)
    clip = c.get("/api/clips").json()["clips"][0]
    assert clip["game"]["name"] == "Counter-Strike 2"
    assert clip["game"]["steam_appid"] == 730
    assert clip["recorded_at"] == "2026-11-10T21:15:32"
    assert c.get(f"/t/{clip['id']}.jpg").status_code == 200

    c.post("/api/logout")
    c.cookies.clear()
    private = c.get(f"/w/{clip['id']}", follow_redirects=False)       # visitors are asked to sign in
    assert private.status_code == 303 and private.headers["location"].startswith("/login?next=%2Fw%2F")
    assert c.get(f"/v/{clip['id']}.mp4").status_code == 404
    assert c.patch(f"/api/clips/{clip['id']}", json={"title": "x"}).status_code == 401

    login(c)
    assert c.patch(f"/api/clips/{clip['id']}", json={"visibility": "unlisted"}).status_code == 200
    c.cookies.clear()
    page = c.get(f"/w/{clip['id']}")
    assert page.status_code == 200 and 'property="og:video"' in page.text
    assert c.get("/api/clips").json()["total"] == 0          # unlisted isn't listed
    part = c.get(f"/v/{clip['id']}.mp4", headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and len(part.content) == 10
    c.post(f"/api/clips/{clip['id']}/view")
    assert c.get(f"/api/clips/{clip['id']}").json()["views"] == 1


def test_move_keeps_id_and_delete_hides(site):
    c = site["client"]
    login(c)
    before = c.get("/api/clips").json()["clips"][0]
    src = site["clips"] / "Counter-Strike 2__2026-11-10__21-15-32.mp4"
    (site["clips"] / "cs").mkdir()
    src.rename(site["clips"] / "cs" / src.name)
    site["scan"]()
    after = c.get("/api/clips").json()["clips"]
    assert [x["id"] for x in after] == [before["id"]]
    assert after[0]["visibility"] == "unlisted"

    (site["clips"] / "cs" / src.name).unlink()
    site["scan"]()
    assert c.get("/api/clips").json()["total"] == 0


def test_half_copied_file_waits(site):
    c = site["client"]
    login(c)
    partial = site["clips"] / "Halo" / "broken.mp4"
    partial.parent.mkdir()
    partial.write_bytes(b"not a video yet")
    old = time.time() - 600
    os.utime(partial, (old, old))
    site["scan"]()
    assert c.get("/api/clips").json()["total"] == 0
    site["add"]("Halo/broken.mp4")          # the copy finishes
    site["scan"]()
    clips = c.get("/api/clips").json()["clips"]
    assert len(clips) == 1 and clips[0]["game"]["name"] == "Halo"


def test_regroup_game(site):
    c = site["client"]
    login(c)
    clip = c.get("/api/clips").json()["clips"][0]
    r = c.patch(f"/api/games/{clip['game']['id']}", json={"name": "Halo Infinite", "steam_appid": 1240440})
    assert r.status_code == 200
    game = c.get(f"/api/clips/{clip['id']}").json()["game"]
    assert (game["name"], game["steam_appid"]) == ("Halo Infinite", 1240440)
    assert c.patch(f"/api/clips/{clip['id']}", json={"game": ""}).json()["game"] is None
    assert c.get("/api/games").json()["games"] == []        # empty games are pruned


def test_game_metadata_art_and_settings(site):
    c = site["client"]
    login(c)
    site["add"]("Counter-Strike-2__2026-11-11__10-00-00.mp4")
    site["scan"]()
    game = next(g for g in c.get("/api/games").json()["games"] if g["steam_appid"] == 730)
    assert game["name"] == "Counter-Strike 2"                 # Steam's spelling, not "Counter Strike 2"
    assert c.get(f"/api/clips?game={game['id']}").json()["clips"][0]["title"].startswith("Counter-Strike 2 · ")
    assert game["description"] == "A tactical shooter." and game["developer"] == "Valve"
    assert game["cover"] and game["hero"] and not game["art_locked"]
    assert c.get(game["cover"]).status_code == 200

    labels = [a["label"] for a in c.get(f"/api/games/{game['id']}/art").json()["art"]]
    assert labels[:2] == ["Header", "Capsule"] and "Screenshot 1" in labels
    picked = c.post(f"/api/games/{game['id']}/art/hero", json={"url": "https://img.test/s1.jpg"}).json()
    assert picked["art_locked"] and picked["hero"] != game["hero"]
    assert c.put(f"/api/games/{game['id']}/art/cover", content=b"not an image").status_code == 400
    assert not c.delete(f"/api/games/{game['id']}/art").json()["art_locked"]

    clip = c.get(f"/api/clips?game={game['id']}").json()["clips"][0]
    custom = c.post(f"/api/clips/{clip['id']}/thumbnail", json={"time": 1.2}).json()
    assert custom["thumb_custom"] and custom["thumb"] != clip["thumb"]
    assert c.post("/api/clips/bulk", json={"ids": [clip["id"]], "visibility": "public"}).json()["updated"] == 1

    assert c.patch("/api/settings", json={"accent": "blue"}).status_code == 400
    assert c.patch("/api/settings", json={"filename_pattern": "("}).status_code == 400
    r = c.patch("/api/settings", json={"site_name": "My Clips", "accent": "#3366ff", "show_views": False})
    assert r.json()["values"]["site_name"] == "My Clips"
    assert "My Clips" in c.get("/").text and "#3366ff" in c.get("/").text
    c.cookies.clear()
    assert c.get("/api/settings").status_code == 401
    assert c.get(f"/api/clips/{clip['id']}").json()["views"] is None
    test = {"filename": "2026-01-02 03-04-05 - Halo.mp4", "pattern": r"^(?P<date>[\d-]+) (?P<time>[\d-]+) - (?P<game>.+)$"}
    login(c)
    assert c.post("/api/settings/test-filename", json=test).json()["game"] == "Halo"
    assert c.get("/api/stats").json()["clips"] == 2


def test_trim(site):
    c = site["client"]
    login(c)
    site["add"]("Trimtest__2026-11-01__10-00-00.mp4")
    site["scan"]()
    clip = next(x for x in c.get("/api/clips").json()["clips"] if x["filename"].startswith("Trimtest"))
    assert clip["duration"] == 2.0 and clip["trim_start"] is None

    def wait():
        for _ in range(100):
            now = c.get(f"/api/clips/{clip['id']}").json()
            if not now["processing"]:
                return now
            time.sleep(0.1)
        raise AssertionError("trim never finished")

    assert c.post(f"/api/clips/{clip['id']}/trim", json={"start": 0.5, "end": 0.7}).status_code == 400
    assert c.post(f"/api/clips/{clip['id']}/trim", json={"start": 0.5, "end": 1.5}).json()["processing"]
    done = wait()
    assert (done["trim_start"], done["trim_end"], done["source_duration"]) == (0.5, 1.5, 2.0)
    assert 0.9 <= done["duration"] <= 1.1 and done["video"] != clip["video"]
    original = site["clips"] / "Trimtest__2026-11-01__10-00-00.mp4"
    served = c.get(done["video"]).content
    assert served != original.read_bytes()                                   # visitors get the cut copy
    assert c.get(f"/v/{clip['id']}.mp4?original=true").content == original.read_bytes()
    site["scan"]()                                                           # a rescan leaves the trim alone
    assert c.get(f"/api/clips/{clip['id']}").json()["trim_start"] == 0.5

    c.post(f"/api/clips/{clip['id']}/trim", json={"start": None})
    back = wait()
    assert back["trim_start"] is None and back["duration"] == 2.0
    assert c.get(back["video"]).content == original.read_bytes()
    c.cookies.clear()
    assert c.get(f"/v/{clip['id']}.mp4?original=true").status_code in (401, 404)


def test_highlight_as_new_clip(site):
    c = site["client"]
    login(c)
    parent = next(x for x in c.get("/api/clips").json()["clips"] if x["filename"].startswith("Trimtest"))
    total = c.get("/api/clips").json()["total"]
    new = c.post(f"/api/clips/{parent['id']}/trim", json={"start": 0.2, "end": 1.2, "as_new": True, "title": "Best bit"}).json()
    assert new["id"] != parent["id"] and new["highlight"] and new["title"] == "Best bit"
    for _ in range(100):
        new = c.get(f"/api/clips/{new['id']}").json()
        if not new["processing"]:
            break
        time.sleep(0.1)
    assert 0.9 <= new["duration"] <= 1.1 and new["game"]["name"] == "Trimtest"
    assert c.get(f"/api/clips/{parent['id']}").json()["duration"] == 2.0      # the full clip is untouched
    site["scan"]()
    assert c.get("/api/clips").json()["total"] == total + 1                    # survives a rescan
    original = site["clips"] / "Trimtest__2026-11-01__10-00-00.mp4"
    assert c.get(new["video"]).content != original.read_bytes()
    assert c.post(f"/api/clips/{new['id']}/trim", json={"start": None}).status_code == 400

    # Deleting the highlight's file never touches the recording it came from.
    assert c.post("/api/clips/delete", json={"ids": [new["id"]], "file": True}).json()["deleted"] == 1
    assert original.exists() and c.get("/api/clips").json()["total"] == total


def test_installable(site):
    c = site["client"]
    manifest = c.get("/manifest.webmanifest").json()
    assert manifest["display"] == "standalone" and len(manifest["icons"]) == 3
    icon = c.get(manifest["icons"][0]["src"])
    assert icon.status_code == 200 and icon.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert c.get("/icons/64.png").status_code == 404
    assert c.get("/sw.js").status_code == 200 and "<svg" in c.get("/icon.svg").text
    assert 'rel="manifest"' in c.get("/").text


def test_login_wall(site):
    c = site["client"]
    login(c)
    clips = c.get("/api/clips").json()["clips"]
    shared = clips[0]["id"]
    c.patch(f"/api/clips/{shared}", json={"visibility": "unlisted"})
    assert c.patch("/api/settings", json={"public_library": False}).status_code == 200
    assert c.get("/", follow_redirects=False).status_code == 200            # signed in
    assert c.get("/login", follow_redirects=False).headers["location"] == "/"
    c.cookies.clear()

    home = c.get("/", follow_redirects=False)
    assert home.status_code == 303 and home.headers["location"] == "/login"
    assert c.get("/settings", follow_redirects=False).headers["location"] == "/login?next=%2Fsettings"
    assert c.get("/api/clips").status_code == 401 and c.get("/api/games").status_code == 401
    page = c.get("/login?next=https://evil.example/")
    assert page.status_code == 200 and "evil.example" not in page.text and 'autocomplete="username"' in page.text
    # Shared links still work without signing in.
    assert c.get(f"/w/{shared}").status_code == 200
    assert c.get(f"/v/{shared}.mp4", headers={"Range": "bytes=0-9"}).status_code == 206
    assert c.get(f"/t/{shared}.jpg").status_code == 200
    login(c)
    c.patch("/api/settings", json={"public_library": True})


def test_change_account(site):
    c = site["client"]
    login(c)
    assert c.post("/api/account", json={"current": "wrong", "new": "secret123"}).status_code == 401
    assert c.post("/api/account", json={"current": "pw", "username": "bad name!"}).status_code == 400
    assert c.post("/api/account", json={"current": "pw", "username": "boss", "new": "secret123"}).json()["username"] == "boss"
    assert c.get("/api/settings").status_code == 200           # this browser stays signed in
    c.cookies.clear()
    assert c.post("/api/login", json={"username": "admin", "password": "secret123"}).status_code == 401
    assert c.post("/api/login", json={"username": "boss", "password": "pw"}).status_code == 401
    assert c.post("/api/login", json={"username": "Boss", "password": "secret123"}).status_code == 200


def test_steamgriddb_art(site, monkeypatch):
    from app import sgdb
    c = site["client"]
    login(c)
    calls = []

    def fake_call(path, key=None):
        calls.append(path)
        if key == "bad":
            raise sgdb.SgdbError("SteamGridDB didn't accept the API key")
        if path.startswith("/search/autocomplete/"):
            return [{"id": 77, "name": "Fortnite"}]
        if path.startswith("/games/steam/"):
            return {"id": 5, "name": "Counter-Strike 2"}
        return [{"url": "https://cdn.test/a.png", "thumb": "https://cdn.test/a_t.png", "author": {"name": "someone"}}]
    monkeypatch.setattr(sgdb, "_call", fake_call)

    assert c.put("/api/settings/steamgriddb-key", json={"key": "bad"}).status_code == 400
    assert c.put("/api/settings/steamgriddb-key", json={"key": "good"}).json()["steamgriddb_key_set"]
    assert c.get("/api/me").json()["sgdb"] is True

    game = next(g for g in c.get("/api/games").json()["games"] if g["steam_appid"] == 730)
    r = c.get(f"/api/games/{game['id']}/art?source=sgdb&slot=hero").json()
    assert r["matched"] == "Counter-Strike 2" and r["art"][0]["label"] == "by someone"
    assert any(p.startswith("/heroes/game/5") for p in calls)
    assert c.get(f"/api/games/{game['id']}/art?source=sgdb&slot=cover&q=fort").json()["matched"] == "Fortnite"

    # A game Steam doesn't know gets SteamGridDB artwork on its own.
    from app import games as games_mod
    monkeypatch.setattr(games_mod, "steam_search", lambda term: [])
    site["add"]("Fortnite__2026-11-12__10-00-00.mp4")
    site["scan"]()
    fortnite = next(g for g in c.get("/api/games").json()["games"] if g["name"] == "Fortnite")
    assert fortnite["steam_appid"] is None and fortnite["cover"] and fortnite["hero"]
    assert c.put("/api/settings/steamgriddb-key", json={"key": ""}).json()["steamgriddb_key_set"] is False


def test_delete_clips(site):
    c = site["client"]
    login(c)
    path = site["add"]("Fortnite__2026-11-13__10-00-00.mp4")
    keep = site["add"]("Fortnite__2026-11-14__10-00-00.mp4")
    site["scan"]()
    by_file = {x["filename"]: x for x in c.get("/api/clips").json()["clips"]}
    first, second = by_file[path.name], by_file[keep.name]
    total = c.get("/api/clips").json()["total"]

    # Remove from library: file stays and is not imported again.
    assert c.post("/api/clips/delete", json={"ids": [first["id"]]}).json()["deleted"] == 1
    site["scan"]()
    assert path.exists() and c.get("/api/clips").json()["total"] == total - 1
    assert c.get(f"/w/{first['id']}").status_code == 404           # signed in: a plain "not found"
    assert c.get("/api/stats").json()["removed"] == 1
    assert c.post("/api/maintenance/restore-removed").status_code == 200
    for _ in range(50):
        if c.get("/api/clips").json()["total"] == total:
            break
        time.sleep(0.1)
    assert c.get("/api/clips").json()["total"] == total

    # Delete the file itself.
    assert c.get("/api/me").json()["can_delete_files"] is True
    assert c.post("/api/clips/delete", json={"ids": [second["id"]], "file": True}).json()["deleted"] == 1
    assert not keep.exists() and not (site["data"] / "thumbs" / f"{second['id']}.jpg").exists()
    c.cookies.clear()
    assert c.post("/api/clips/delete", json={"ids": [first["id"]]}).status_code == 401
