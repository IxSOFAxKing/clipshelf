from datetime import datetime

import pytest

from app import games


@pytest.mark.parametrize("path, game, when", [
    ("Counter-Strike 2__2026-11-10__21-15-32.mp4", "Counter-Strike 2", datetime(2026, 11, 10, 21, 15, 32)),
    ("Rocket League 2026.09.14 - 18.22.05.01.DVR.mp4", "Rocket League", datetime(2026, 9, 14, 18, 22, 5)),
    ("Apex_Legends_2025-01-02_03-04-05.mp4", "Apex Legends", datetime(2025, 1, 2, 3, 4, 5)),
    ("Hades II 20250102_030405.mp4", "Hades II", datetime(2025, 1, 2, 3, 4, 5)),
    ("Left 4 Dead 2 2024-05-06 07-08-09.mkv", "Left 4 Dead 2", datetime(2024, 5, 6, 7, 8, 9)),
    ("ARC-Raiders__2026-09-12__00-31-35.mp4", "ARC Raiders", datetime(2026, 9, 12, 0, 31, 35)),
    ("Call-of-Duty®-Modern-Warfare-3__2026-03-01__10-11-12.mp4", "Call of Duty® Modern Warfare 3", datetime(2026, 3, 1, 10, 11, 12)),
    ("WARDOGS__2026-11-15__00-25-03_trim.mp4", "WARDOGS", datetime(2026, 11, 15, 0, 25, 3)),
    ("DESKTOPCAPTURE__2026-02-21__00-09-10.mp4", None, datetime(2026, 2, 21, 0, 9, 10)),
    ("Halo/funny bounce.mp4", "Halo", None),
    ("Halo/Replay 2024-05-06 07-08-09.mp4", "Halo", datetime(2024, 5, 6, 7, 8, 9)),
    ("2024-05-06 07-08-09.mp4", None, datetime(2024, 5, 6, 7, 8, 9)),
    ("random capture.mp4", None, None),
])
def test_parse_clip_path(path, game, when):
    assert games.parse_clip_path(path) == (game, when)


def test_best_match():
    results = [
        {"appid": 2622380, "name": "ELDEN RING NIGHTREIGN"},
        {"appid": 1245620, "name": "ELDEN RING"},
        {"appid": 252950, "name": "Rocket League®"},
    ]
    assert games.best_match("Elden Ring", results)["appid"] == 1245620
    assert games.best_match("Rocket League", results)["appid"] == 252950
    assert games.best_match("Halo", results) is None
    assert games.best_match("Halo", []) is None


def test_trim_title_and_name_folding(tmp_path):
    assert games.default_title("WARDOGS__2026-11-15__00-25-03_trim.mp4", "WARDOGS", datetime(2026, 11, 15, 0, 25, 3)).endswith("(trimmed)")
    assert games.norm("Counter Strike 2") == games.norm("Counter-Strike 2")
    assert games.norm("Call of Duty®") == games.norm("call of duty")
