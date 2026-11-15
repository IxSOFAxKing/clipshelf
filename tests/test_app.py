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
    from app import games
    from app.main import app
    from app.scanner import scanner

    def fake_get(url, timeout=15):
        if "storesearch" in url:
            return json.dumps({"items": [{"type": "app", "id": 730, "name": "Counter-Strike 2", "tiny_image": "x"}]}).encode()
        if "appdetails" in url:
            return json.dumps({"730": {"data": {"name": "Counter-Strike 2", "header_image": "x"}}}).encode()
        return b"\xff\xd8" + b"0" * 2000
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
        yield {"client": client, "clips": clips, "data": data, "scan": scanner.scan_once, "add": add_clip}


def login(client):
    assert client.post("/api/login", json={"password": "pw"}).status_code == 200


def test_import_and_visibility(site):
    c = site["client"]
    site["add"]("Counter-Strike 2__2026-11-10__21-15-32.mp4")
    site["scan"]()

    assert c.get("/api/clips").json()["total"] == 0          # private by default
    assert c.post("/api/login", json={"password": "nope"}).status_code == 401
    login(c)
    clip = c.get("/api/clips").json()["clips"][0]
    assert clip["game"]["name"] == "Counter-Strike 2"
    assert clip["game"]["steam_appid"] == 730
    assert clip["recorded_at"] == "2026-11-10T21:15:32"
    assert c.get(f"/t/{clip['id']}.jpg").status_code == 200

    c.post("/api/logout")
    c.cookies.clear()
    assert c.get(f"/w/{clip['id']}").status_code == 404
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
