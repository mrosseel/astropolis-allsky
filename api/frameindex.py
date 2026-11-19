"""Map each frame of an indi-allsky timelapse to the time it was captured.

indi-allsky prints the capture time in the top right corner of every frame
("2026.10.25 22:32:51", local time). The camera has gaps (restarts, cloud
pauses), so a linear model from the first to the last frame can be off by
more than an hour. This module reads the printed time of every frame with
tesseract and stores one epoch per frame in a JSON index next to the video.
"""

import bisect
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("ALLSKY_TZ", "Europe/Brussels"))

# ffmpeg crop of the timestamp line: width:height:x:y, x and y may use iw/ih.
STAMP_CROP = os.environ.get("STAMP_CROP", "700:70:iw-700:15")

# Fewer readable frames than this fraction means the label moved or changed.
MIN_OK_FRACTION = 0.5

INDEX_VERSION = 1

# Tesseract reads the space between date and time as a random digit,
# so the time is taken from the end of the line.
STAMP_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2}).*?(\d{2}):(\d{2}):(\d{2})\D*$")


def parse_stamp(text: str) -> datetime | None:
    m = STAMP_RE.search(text.strip())
    if not m:
        return None
    try:
        return datetime(*map(int, m.groups()))
    except ValueError:
        return None


def to_epoch(local: list[datetime | None]) -> list[float | None]:
    """Local wall-clock times to epochs. At the autumn DST change the clock
    goes back one hour; a time that is earlier than the one before it is
    read again as the second occurrence (fold=1)."""
    out: list[float | None] = []
    last: float | None = None
    for dt in local:
        if dt is None:
            out.append(None)
            continue
        t = dt.replace(tzinfo=TZ).timestamp()
        if last is not None and t <= last:
            t2 = dt.replace(tzinfo=TZ, fold=1).timestamp()
            if t2 > last:
                t = t2
        out.append(t)
        if last is None or t > last:
            last = t
    return out


def longest_increasing(values: list[float | None]) -> set[int]:
    """Indexes of the longest strictly increasing subsequence. A reading
    outside this set is an OCR error."""
    tails: list[float] = []
    tail_idx: list[int] = []
    prev: dict[int, int] = {}
    for i, v in enumerate(values):
        if v is None:
            continue
        pos = bisect.bisect_left(tails, v)
        if pos == len(tails):
            tails.append(v)
            tail_idx.append(i)
        else:
            tails[pos] = v
            tail_idx[pos] = i
        prev[i] = tail_idx[pos - 1] if pos > 0 else -1
    keep: set[int] = set()
    i = tail_idx[-1] if tail_idx else -1
    while i != -1:
        keep.add(i)
        i = prev[i]
    return keep


def fill_gaps(values: list[float | None]) -> list[float]:
    """Linear interpolation for unread frames. Frames before the first or
    after the last reading are extrapolated one frame period at a time."""
    known = [i for i, v in enumerate(values) if v is not None]
    if len(known) < 2:
        raise ValueError("fewer than two readable frames")
    out = [0.0] * len(values)
    for i in known:
        out[i] = values[i]
    for a, b in zip(known, known[1:]):
        step = (values[b] - values[a]) / (b - a)
        for i in range(a + 1, b):
            out[i] = values[a] + step * (i - a)
    first, last = known[0], known[-1]
    period = (values[last] - values[first]) / (last - first)
    for i in range(first):
        out[i] = values[first] - period * (first - i)
    for i in range(last + 1, len(values)):
        out[i] = values[last] + period * (i - last)
    return out


def build_times(readings: list[str]) -> tuple[list[float], int]:
    """OCR text per frame to one epoch per frame, and the count of frames
    whose own reading was used."""
    epochs = to_epoch([parse_stamp(r) for r in readings])
    keep = longest_increasing(epochs)
    clean = [e if i in keep else None for i, e in enumerate(epochs)]
    if len(keep) < MIN_OK_FRACTION * len(readings):
        raise ValueError(f"only {len(keep)} of {len(readings)} frames readable")
    return fill_gaps(clean), len(keep)


def probe_video(path: Path) -> tuple[int, float]:
    """Frame count and frame rate."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
        "-show_entries", "stream=nb_read_packets,r_frame_rate",
        "-of", "json", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
    stream = json.loads(proc.stdout)["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    return int(stream["nb_read_packets"]), int(num) / int(den)


def ocr_video(path: Path) -> list[str]:
    """Printed timestamp text of every frame, in frame order."""
    with tempfile.TemporaryDirectory(prefix="allsky-ocr-") as tmp:
        tmpdir = Path(tmp)
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-nostdin", "-i", str(path),
                "-vf", f"crop={STAMP_CROP},format=gray,negate",
                str(tmpdir / "%06d.png"),
            ],
            check=True, timeout=3600,
        )
        pngs = sorted(tmpdir.glob("*.png"))
        listfile = tmpdir / "list.txt"
        listfile.write_text("".join(f"{p}\n" for p in pngs))
        subprocess.run(
            [
                "tesseract", str(listfile), str(tmpdir / "out"),
                "--psm", "7", "-c", "tessedit_char_whitelist=0123456789.:",
            ],
            check=True, timeout=3600, capture_output=True,
        )
        pages = (tmpdir / "out.txt").read_text().split("\f")
    return (pages + [""] * len(pngs))[: len(pngs)]


def index_path(video: Path) -> Path:
    return video.parent / "index" / (video.stem + ".json")


def build_index(video: Path) -> dict:
    frames, fps = probe_video(video)
    readings = ocr_video(video)
    if len(readings) != frames:
        raise ValueError(f"decoded {len(readings)} frames, expected {frames}")
    times, ok = build_times(readings)
    return {
        "version": INDEX_VERSION,
        "video": video.name,
        "fps": fps,
        "frames": frames,
        "ocr_ok": ok,
        "t": [round(t, 1) for t in times],
    }


def write_index(video: Path, index: dict) -> Path:
    out = index_path(video)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, separators=(",", ":")))
    tmp.replace(out)
    return out


def load_index(video: Path) -> dict | None:
    try:
        index = json.loads(index_path(video).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if index.get("version") != INDEX_VERSION:
        return None
    return index


def frame_range(times: list[float], start: float, end: float) -> tuple[int, int] | None:
    """First and last frame with a capture time in [start, end]."""
    i0 = bisect.bisect_left(times, start)
    i1 = bisect.bisect_right(times, end) - 1
    if i0 > i1:
        return None
    return i0, i1
