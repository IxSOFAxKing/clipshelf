import os
import sys
import tempfile
from pathlib import Path

# Configuration is read from the environment when the app is imported.
_root = Path(tempfile.mkdtemp(prefix="clipshelf-test-"))
(_root / "clips").mkdir()
os.environ.update(CLIPS_DIR=str(_root / "clips"), DATA_DIR=str(_root / "data"),
                  ADMIN_PASSWORD="pw", SCAN_INTERVAL="3600")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
