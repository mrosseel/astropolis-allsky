"""Public API: cut a clip from the timelapse around a given date and time."""

import json
import os
import subprocess
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import frameindex

VIDEOS_DIR = Path(os.environ.get("VIDEOS_DIR", "./videos"))
CLIP_DIR = Path(os.environ.get("CLIP_DIR", VIDEOS_DIR / "custom"))
PUBLIC_VIDEO_BASE = os.environ.get(
    "PUBLIC_VIDEO_BASE", "https://files.astropolis.be/public/allsky/videos"
).rstrip("/")
PUBLIC_CLIP_BASE = os.environ.get("PUBLIC_CLIP_BASE", PUBLIC_VIDEO_BASE + "/custom").rstrip("/")
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "https://allsky.astropolis.be")
VIEW_SIZE = int(os.environ.get("VIEW_SIZE", "1080"))

MAX_WINDOW_MIN = 120
MAX_FRAMES = 1000
# One encode at a time: a full-resolution encode uses all CPU cores.
ENCODE_WAIT_S = 300

app = FastAPI(title="allsky-moment-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

encode_lock = threading.Lock()


class MomentRequest(BaseModel):
    date: date
    time: time
    before_min: float = Field(ge=0, le=MAX_WINDOW_MIN)
    after_min: float = Field(ge=0, le=MAX_WINDOW_MIN)
    fps: int = Field(default=10, ge=1, le=25)


def video_file(day: date, tod: str) -> Path:
    return VIDEOS_DIR / f"allsky-timelapse_ccd1_{day:%Y%m%d}_{tod}.mp4"


def local_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, frameindex.TZ).isoformat(timespec="seconds")


def candidates(day: date) -> list[tuple[Path, dict]]:
    """Indexed videos that can hold a moment on this calendar day: the
    night that started the evening before, the day, and the night."""
    out = []
    for d, tod in ((day - timedelta(days=1), "night"), (day, "day"), (day, "night")):
        path = video_file(d, tod)
        if not path.exists():
            continue
        index = frameindex.load_index(path)
        if index is not None:
            out.append((path, index))
    return out


def coverage(items: list[tuple[Path, dict]]) -> list[dict]:
    return [
        {"video": p.name, "start": local_iso(ix["t"][0]), "end": local_iso(ix["t"][-1])}
        for p, ix in items
    ]


def encode(src: Path, i0: int, i1: int, src_fps: float, fps: int, full: Path, view: Path) -> None:
    # Seek a quarter frame before frame i0 so float rounding cannot skip it.
    seek = max(0.0, (i0 - 0.25) / src_fps)
    full_tmp = full.with_name(full.stem + ".part.mp4")
    view_tmp = view.with_name(view.stem + ".part.mp4")
    frames = str(i1 - i0 + 1)
    x264 = [
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-r", str(fps), "-frames:v", frames,
    ]
    cmd = [
        "ffmpeg", "-v", "error", "-nostdin", "-y",
        "-ss", f"{seek:.4f}", "-i", str(src),
        "-filter_complex",
        f"[0:v]setpts=N/({fps}*TB),split=2[full][v];[v]scale={VIEW_SIZE}:-2[view]",
        "-map", "[full]", *x264, "-preset", "fast", "-crf", "20", str(full_tmp),
        "-map", "[view]", *x264, "-preset", "medium", "-crf", "23", str(view_tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        for p in (full_tmp, view_tmp):
            p.unlink(missing_ok=True)
        raise HTTPException(500, f"ffmpeg failed: {proc.stderr[-400:]}")
    full_tmp.replace(full)
    view_tmp.replace(view)


@app.get("/api/ping")
def ping() -> dict:
    return {"ok": True}


@app.get("/api/moment/coverage")
def get_coverage(day: date = Query(alias="date")) -> dict:
    return {"date": day.isoformat(), "videos": coverage(candidates(day))}


@app.post("/api/moment")
def create_moment(req: MomentRequest) -> dict:
    center = datetime.combine(req.date, req.time, frameindex.TZ).timestamp()
    items = candidates(req.date)
    match = next(((p, ix) for p, ix in items if ix["t"][0] <= center <= ix["t"][-1]), None)
    if match is None:
        raise HTTPException(
            404,
            {"message": "Geen beelden voor dit tijdstip.", "coverage": coverage(items)},
        )
    src, index = match
    times = index["t"]
    start = center - req.before_min * 60
    end = center + req.after_min * 60
    rng = frameindex.frame_range(times, start, end)
    if rng is None:
        raise HTTPException(404, {"message": "Geen beelden in dit venster.", "coverage": coverage(items)})
    i0, i1 = rng
    if i1 - i0 + 1 > MAX_FRAMES:
        raise HTTPException(400, {"message": f"Venster te groot: meer dan {MAX_FRAMES} beelden."})

    stem = f"clip_{src.stem.removeprefix('allsky-timelapse_')}_{i0}-{i1}_{req.fps}fps"
    full = CLIP_DIR / f"{stem}.mp4"
    view = CLIP_DIR / f"{stem}.view.mp4"
    meta_path = CLIP_DIR / f"{stem}.json"

    cached = full.exists() and view.exists() and meta_path.exists()
    if not cached:
        if not encode_lock.acquire(timeout=ENCODE_WAIT_S):
            raise HTTPException(503, {"message": "Server bezig, probeer later opnieuw."})
        try:
            CLIP_DIR.mkdir(parents=True, exist_ok=True)
            # Another request can have made the same clip during the wait.
            if not (full.exists() and view.exists()):
                encode(src, i0, i1, index["fps"], req.fps, full, view)
        finally:
            encode_lock.release()

    frames = i1 - i0 + 1
    meta = {
        "full_url": f"{PUBLIC_CLIP_BASE}/{full.name}",
        "view_url": f"{PUBLIC_CLIP_BASE}/{view.name}",
        "source": {"video": src.name, "url": f"{PUBLIC_VIDEO_BASE}/{src.name}"},
        "requested": {"start": local_iso(start), "end": local_iso(end)},
        "start": local_iso(times[i0]),
        "end": local_iso(times[i1]),
        "frames": frames,
        "fps": req.fps,
        "duration_s": round(frames / req.fps, 2),
        # True when the window runs past the start or end of this video.
        "clamped": start < times[0] or end > times[-1],
    }
    if not cached:
        meta_path.write_text(json.dumps(meta, indent=2))
    return {**meta, "cached": cached}
