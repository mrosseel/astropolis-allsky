import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SOURCE_BASE_URL = os.environ.get(
    "SOURCE_BASE_URL", "https://files.astropolis.be/public/allsky/videos"
).rstrip("/")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./clips")).expanduser()
PUBLIC_CLIP_BASE = os.environ.get(
    "PUBLIC_CLIP_BASE", "https://files.astropolis.be/public/allsky/videos/custom"
).rstrip("/")
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "*")

SHARE_DIR = OUTPUT_DIR / "share"
PREVIEW_DIR = SHARE_DIR / "preview"
LOGO_PATH = Path(os.environ.get("LOGO_PATH", OUTPUT_DIR.parent / "logo.svg"))
REMOTION_IMAGE = os.environ.get("REMOTION_IMAGE", "allsky-remotion:latest")
PODMAN_BIN = os.environ.get("PODMAN_BIN", "podman")
FPS = 30

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SHARE_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
LOGO_PATH.parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="allsky-video-api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ORIGIN] if CORS_ORIGIN != "*" else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_password(x_admin_password: str = Header(default="")) -> None:
    if not ADMIN_PASSWORD or x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="unauthorized")


class ClipRequest(BaseModel):
    source_filename: str = Field(pattern=r"^[A-Za-z0-9_.-]+\.mp4$", max_length=200)
    center_s: float = Field(ge=0)
    before_s: float = Field(ge=0)
    after_s: float = Field(ge=0)
    label: str | None = Field(default=None, max_length=60)


class EventSpec(BaseModel):
    text: str = Field(max_length=80)
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)


class ShareClipRequest(BaseModel):
    clip_filename: str = Field(pattern=r"^clip_[A-Za-z0-9_.-]+\.mp4$", max_length=200)
    date_location: str = Field(max_length=120)
    aspect: str = Field(pattern=r"^(16:9|9:16|1:1)$")
    event: EventSpec | None = None


class SharePreviewRequest(ShareClipRequest):
    time_s: float | None = Field(default=None, ge=0)


SAFE_LABEL = re.compile(r"[^a-zA-Z0-9_-]+")
SAFE_FILENAME = re.compile(r"^clip_[A-Za-z0-9_.-]+\.mp4$")
DATE_IN_NAME = re.compile(r"(\d{8})")


def slugify(label: str) -> str:
    return SAFE_LABEL.sub("-", label.strip()).strip("-").lower()[:40]


def probe_duration_s(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise HTTPException(500, f"ffprobe failed: {proc.stderr[-400:]}")
    try:
        return float(proc.stdout.strip())
    except ValueError as e:
        raise HTTPException(500, "could not parse duration") from e


def remotion_props(req: ShareClipRequest, duration_s: float) -> dict:
    duration_frames = max(1, round(duration_s * FPS))
    event = None
    if req.event:
        start_f = max(0, round(req.event.start_s * FPS))
        end_f = min(duration_frames, max(start_f + 1, round(req.event.end_s * FPS)))
        event = {"text": req.event.text, "startFrame": start_f, "endFrame": end_f}
    return {
        "source": "file:///source/" + req.clip_filename,
        "dateLocation": req.date_location,
        "aspect": req.aspect,
        "durationInFrames": duration_frames,
        "event": event,
    }


def params_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def composition_id(aspect: str) -> str:
    return "ShareClip_" + aspect.replace(":", "x")


def podman_render(
    clip_path: Path,
    out_path: Path,
    props: dict,
    mode: str,
    frame: int | None = None,
) -> None:
    """mode: 'render' for mp4, 'still' for single-frame jpg."""
    props_json = json.dumps(props)
    cmd = [
        PODMAN_BIN, "run", "--rm",
        "-v", f"{clip_path.parent}:/source:ro",
        "-v", f"{out_path.parent}:/output",
    ]
    if LOGO_PATH.exists():
        cmd += ["-v", f"{LOGO_PATH}:/app/public/logo.svg:ro"]
    cmd += [REMOTION_IMAGE, mode, composition_id(props["aspect"])]
    if mode == "still" and frame is not None:
        cmd += ["--frame", str(frame)]
    cmd += [
        f"/output/{out_path.name}",
        f"--props={props_json}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise HTTPException(500, f"remotion {mode} failed: {proc.stderr[-500:]}")


@app.get("/api/ping")
def ping() -> dict:
    return {"ok": True}


@app.post("/api/auth", dependencies=[Depends(require_password)])
def check_auth() -> dict:
    return {"ok": True}


@app.post("/api/clip", dependencies=[Depends(require_password)])
def create_clip(req: ClipRequest) -> dict:
    start = max(0.0, req.center_s - req.before_s)
    end = req.center_s + req.after_s
    if end <= start:
        raise HTTPException(400, "empty range")

    src_url = f"{SOURCE_BASE_URL}/{req.source_filename}"
    date_match = DATE_IN_NAME.search(req.source_filename)
    date_tag = date_match.group(1) if date_match else "unknown"

    suffix = slugify(req.label) if req.label else uuid.uuid4().hex[:6]
    slug = f"clip_{date_tag}_c{int(req.center_s)}_{suffix}.mp4"
    if not SAFE_FILENAME.match(slug):
        raise HTTPException(400, "bad filename")

    out_path = OUTPUT_DIR / slug
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{start:.3f}",
        "-to", f"{end:.3f}",
        "-i", src_url,
        "-c", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise HTTPException(500, f"ffmpeg failed: {proc.stderr[-500:]}")

    meta = {
        "filename": slug,
        "url": f"{PUBLIC_CLIP_BASE}/{slug}",
        "created": datetime.now(timezone.utc).isoformat(),
        "source": {"filename": req.source_filename, "url": src_url},
        "center_s": req.center_s,
        "before_s": req.before_s,
        "after_s": req.after_s,
        "label": req.label,
    }
    out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return meta


@app.get("/api/clips", dependencies=[Depends(require_password)])
def list_clips() -> list[dict]:
    items: list[dict] = []
    for p in OUTPUT_DIR.glob("clip_*.json"):
        try:
            items.append(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    items.sort(key=lambda m: m.get("created", ""), reverse=True)
    return items


@app.delete("/api/clips/{filename}", dependencies=[Depends(require_password)])
def delete_clip(filename: str) -> dict:
    if not SAFE_FILENAME.match(filename):
        raise HTTPException(400, "bad name")
    mp4 = OUTPUT_DIR / filename
    meta = mp4.with_suffix(".json")
    for p in (mp4, meta):
        if p.exists():
            p.unlink()
    return {"ok": True}


@app.post("/api/share-clip", dependencies=[Depends(require_password)])
def create_share_clip(req: ShareClipRequest) -> dict:
    clip_path = OUTPUT_DIR / req.clip_filename
    if not clip_path.exists():
        raise HTTPException(404, "clip not found")

    duration_s = probe_duration_s(clip_path)
    props = remotion_props(req, duration_s)
    h = params_hash(props)
    out_name = f"share_{h}.mp4"
    out_path = SHARE_DIR / out_name
    public_url = f"{PUBLIC_CLIP_BASE}/share/{out_name}"

    if out_path.exists():
        return {"filename": out_name, "url": public_url, "cached": True}

    podman_render(clip_path, out_path, props, mode="render")

    meta = {
        "filename": out_name,
        "url": public_url,
        "created": datetime.now(timezone.utc).isoformat(),
        "source_clip": req.clip_filename,
        "props": props,
    }
    out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return {"filename": out_name, "url": public_url, "cached": False}


@app.post("/api/share-clip/preview", dependencies=[Depends(require_password)])
def share_clip_preview(req: SharePreviewRequest) -> dict:
    clip_path = OUTPUT_DIR / req.clip_filename
    if not clip_path.exists():
        raise HTTPException(404, "clip not found")

    duration_s = probe_duration_s(clip_path)
    props = remotion_props(req, duration_s)

    if req.time_s is not None:
        frame = max(0, min(props["durationInFrames"] - 1, round(req.time_s * FPS)))
    elif props["event"]:
        frame = (props["event"]["startFrame"] + props["event"]["endFrame"]) // 2
    else:
        frame = props["durationInFrames"] // 2

    key = {**props, "_frame": frame}
    h = params_hash(key)
    out_name = f"preview_{h}.jpg"
    out_path = PREVIEW_DIR / out_name
    public_url = f"{PUBLIC_CLIP_BASE}/share/preview/{out_name}"

    if out_path.exists():
        return {"url": public_url, "frame": frame, "cached": True}

    podman_render(clip_path, out_path, props, mode="still", frame=frame)
    return {"url": public_url, "frame": frame, "cached": False}


@app.post("/api/logo", dependencies=[Depends(require_password)])
async def upload_logo(file: UploadFile = File(...)) -> dict:
    if file.content_type != "image/svg+xml":
        raise HTTPException(400, "logo must be SVG")
    with LOGO_PATH.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    return {"ok": True, "path": str(LOGO_PATH)}
