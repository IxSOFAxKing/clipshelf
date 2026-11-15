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


def make_thumbnail(src: Path, dest: Path, duration: float, at: float | None = None) -> bool:
    """Grab a frame as a 640px-wide JPEG: at `at` seconds, or a little way in."""
    times = (min(duration * 0.35, max(duration - 0.5, 0)), 0) if at is None else (max(0.0, min(at, duration)),)
    for at in times:
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


def render(src: Path, dest: Path, audio_tracks: int, merge: bool,
           start: float | None = None, end: float | None = None, exact: bool = True) -> bool:
    """Write the copy of a clip that is served to browsers: optionally cut to
    start..end (seconds) and/or with all audio tracks mixed into one.

    `exact` re-encodes the video so the cut lands on the chosen frame; without
    it the video is copied untouched and the cut snaps back to a keyframe."""
    tmp = dest.with_suffix(".tmp.mp4")
    trimming = start is not None or end is not None
    reencode = trimming and exact
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-i", str(src)]
    if merge and audio_tracks > 1:
        inputs = "".join(f"[0:a:{i}]" for i in range(audio_tracks))
        cmd += ["-filter_complex", f"{inputs}amix=inputs={audio_tracks}:normalize=0[a]",
                "-map", "0:v:0", "-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0?"]
        cmd += ["-c:a", "aac", "-b:a", "192k"] if reencode else ["-c:a", "copy"]
    if reencode:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy", "-avoid_negative_ts", "make_zero"]
    cmd += ["-movflags", "+faststart", str(tmp)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=3600, check=True)
        tmp.replace(dest)
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        err = getattr(exc, "stderr", b"") or b""
        log.warning("ffmpeg failed for %s: %s %s", src, exc, err.decode(errors="replace")[-300:])
        tmp.unlink(missing_ok=True)
        return False


def image_to_jpeg(blob: bytes, dest: Path, max_width: int) -> bool:
    """Convert any image ffmpeg can read (JPEG, PNG, WebP, ...) to a JPEG no
    wider than `max_width`. Returns False if the data isn't an image."""
    src = dest.with_suffix(".upload")
    tmp = dest.with_suffix(".tmp.jpg")
    try:
        src.write_bytes(blob)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-frames:v", "1",
             "-vf", f"scale='min({max_width},iw)':-2", "-q:v", "3", str(tmp)],
            capture_output=True, timeout=60, check=True,
        )
        if tmp.stat().st_size == 0:
            return False
        tmp.replace(dest)
        return True
    except (subprocess.SubprocessError, OSError):
        return False
    finally:
        src.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)


def make_icon(dest: Path, size: int, background: str, foreground: str) -> bool:
    """Draw the app icon (a play triangle on the accent colour) as a PNG."""
    def rgb(color):
        return [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    inside = "gte(X,0.40*W)*lte(abs(Y-0.5*H),(0.72*W-X)*0.70)"
    channels = ":".join(f"{c}='if({inside},{f},{b})'" for c, f, b in zip("rgb", rgb(foreground), rgb(background)))
    tmp = dest.with_suffix(".tmp.png")
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=1024x1024", "-frames:v", "1",
             "-vf", f"format=rgb24,geq={channels},scale={size}:{size}:flags=lanczos", str(tmp)],
            capture_output=True, timeout=60, check=True,
        )
        tmp.replace(dest)
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("Couldn't draw the app icon: %s", exc)
        tmp.unlink(missing_ok=True)
        return False
