"""Make the frame index and the 1080 px web copy of each new timelapse.

Run from a systemd timer. Each run handles the videos that have no index
or no web copy yet, then exits. The full-resolution video is not changed.
"""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

import frameindex

VIDEOS_DIR = Path(os.environ.get("VIDEOS_DIR", "./videos"))
WEB_SIZE = int(os.environ.get("WEB_SIZE", "1080"))
VIDEO_GLOB = "allsky-timelapse_ccd*_*.mp4"

log = logging.getLogger("allsky-indexer")


def web_path(video: Path) -> Path:
    return video.parent / "web" / video.name


def failed_path(video: Path) -> Path:
    return frameindex.index_path(video).with_suffix(".failed")


def make_web_copy(video: Path) -> None:
    out = web_path(video)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.mp4")
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(video),
            "-vf", f"scale={WEB_SIZE}:-2", "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "24",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(tmp),
        ],
        check=True, timeout=3600,
    )
    tmp.replace(out)


def needs_index(video: Path) -> bool:
    if frameindex.load_index(video) is not None:
        return False
    failed = failed_path(video)
    # A failed video is tried again only when a new upload replaces it.
    return not (failed.exists() and failed.stat().st_mtime >= video.stat().st_mtime)


def process(video: Path) -> bool:
    ok = True
    if needs_index(video):
        log.info("indexing %s", video.name)
        try:
            index = frameindex.build_index(video)
        except (subprocess.SubprocessError, ValueError, KeyError) as e:
            log.error("index failed for %s: %s", video.name, e)
            failed = failed_path(video)
            failed.parent.mkdir(parents=True, exist_ok=True)
            failed.write_text(f"{e}\n")
            ok = False
        else:
            frameindex.write_index(video, index)
            log.info("indexed %s: %d/%d frames read", video.name, index["ocr_ok"], index["frames"])
    if not web_path(video).exists():
        log.info("web copy %s", video.name)
        try:
            make_web_copy(video)
        except subprocess.SubprocessError as e:
            log.error("web copy failed for %s: %s", video.name, e)
            ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", nargs="*", type=Path, help="default: all in VIDEOS_DIR")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    videos = args.videos or sorted(VIDEOS_DIR.glob(VIDEO_GLOB))
    results = [process(v) for v in videos]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
