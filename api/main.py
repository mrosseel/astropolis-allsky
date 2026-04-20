import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
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

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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


SAFE_LABEL = re.compile(r"[^a-zA-Z0-9_-]+")
SAFE_FILENAME = re.compile(r"^clip_[A-Za-z0-9_.-]+\.mp4$")
DATE_IN_NAME = re.compile(r"(\d{8})")


def slugify(label: str) -> str:
    return SAFE_LABEL.sub("-", label.strip()).strip("-").lower()[:40]


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
