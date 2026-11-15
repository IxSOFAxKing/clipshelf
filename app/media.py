"""ffprobe / ffmpeg helpers."""
import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("clipshelf.media")

# Codecs that browsers generally play inside an <video> element.
WEB_CODECS = {"h264", "vp8", "vp9", "av1"}


def probe(path: Path) -> dict | None:
    """Return basic stream info, or None if the file isn't a readable video
    (which is also what a half-copied file looks like)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=60, check=True,
        ).stdout
        data = json.loads(out)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        return None
    try:
        duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    except ValueError:
        duration = 0.0
    if duration <= 0:
        return None
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    rotation = 0
    for sd in video.get("side_data_list", []):
        if "rotation" in sd:
            rotation = int(sd["rotation"])
    if abs(rotation) in (90, 270):
        width, height = height, width
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "vcodec": video.get("codec_name") or "",
        "audio_tracks": sum(1 for s in streams if s.get("codec_type") == "audio"),
    }


def make_thumbnail(src: Path, dest: Path, duration: float) -> bool:
    """Grab a frame a little way into the clip as a 640px-wide JPEG."""
    for at in (min(duration * 0.35, max(duration - 0.5, 0)), 0):
        tmp = dest.with_suffix(".tmp.jpg")
        try:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(src),
                 "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", str(tmp)],
                capture_output=True, timeout=120, check=True,
            )
            if tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(dest)
                return True
        except (subprocess.SubprocessError, OSError) as exc:
            log.debug("thumbnail failed for %s at %.2f: %s", src, at, exc)
        tmp.unlink(missing_ok=True)
    return False


def merge_audio(src: Path, dest: Path, tracks: int) -> bool:
    """Write a copy with every audio track mixed into one (video untouched)."""
    tmp = dest.with_suffix(".tmp.mp4")
    inputs = "".join(f"[0:a:{i}]" for i in range(tracks))
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(src),
             "-filter_complex", f"{inputs}amix=inputs={tracks}:normalize=0[a]",
             "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(tmp)],
            capture_output=True, timeout=1800, check=True,
        )
        tmp.replace(dest)
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        err = getattr(exc, "stderr", b"") or b""
        log.warning("audio merge failed for %s: %s %s", src, exc, err.decode(errors="replace")[-300:])
        tmp.unlink(missing_ok=True)
        return False
