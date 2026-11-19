"""Pure image helpers (numpy/cv2 only, no Qt) so they stay easy to test."""
import math
import os
import re

import cv2
import numpy as np

ROTATIONS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def adjust(frame, rotation=0, brightness=0, contrast=0, saturation=0, flip_h=False, flip_v=False):
    """Rotation, mirror (applied after rotation, so it matches what is on screen) and
    brightness/contrast/saturation (-50..50). Returns a new array when something changes."""
    if rotation in ROTATIONS:
        frame = cv2.rotate(frame, ROTATIONS[rotation])
    if flip_h or flip_v:
        frame = cv2.flip(frame, -1 if flip_h and flip_v else 1 if flip_h else 0)
    if brightness or contrast:
        frame = cv2.convertScaleAbs(frame, alpha=1 + contrast / 100, beta=brightness)
    if saturation:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hsv[..., 1] = cv2.convertScaleAbs(hsv[..., 1], alpha=1 + saturation / 100)
        frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return frame


def fit_size(w, h, max_w, max_h):
    """Largest size with the w/h aspect ratio that fits in max_w x max_h."""
    scale = min(max_w / w, max_h / h)
    return max(1, round(w * scale)), max(1, round(h * scale))


def resize(frame, w, h):
    fh, fw = frame.shape[:2]
    if (fw, fh) == (w, h):
        return frame
    return cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA if w < fw else cv2.INTER_LINEAR)


def letterbox(frame, w, h):
    """Fit frame into a black w x h canvas, keeping its aspect ratio, centred."""
    fh, fw = frame.shape[:2]
    nw, nh = fit_size(fw, fh, w, h)
    if (nw, nh) == (w, h):
        return resize(frame, w, h)
    canvas = np.zeros((h, w, 3), np.uint8)
    x, y = (w - nw) // 2, (h - nh) // 2
    canvas[y:y + nh, x:x + nw] = resize(frame, nw, nh)
    return canvas


def draw_label(img, text):
    """Draw a caption bar at the bottom of img, in place. Returns img."""
    h = img.shape[0]
    bar = max(24, h // 25)
    img[h - bar:] = img[h - bar:] // 3
    scale = bar / 40
    # shortcut: Hershey fonts are ASCII only (accents become '?'); switch to QPainter text if that matters
    cv2.putText(img, text, (8, h - bar // 3), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255),
                max(1, round(scale * 2)), cv2.LINE_AA)
    return img


def draw_timestamp(img, text):
    """Draw text on a dark box in the top-left corner, in place. Returns img."""
    h = img.shape[0]
    scale = max(0.5, h / 900)
    thick = max(1, round(scale * 2))
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    pad = int(8 * scale)
    img[:th + base + 2 * pad, :tw + 2 * pad] //= 3
    cv2.putText(img, text, (pad, th + pad), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick, cv2.LINE_AA)
    return img


class MotionDetector:
    """Tells whether a stream changed: share of pixels of a small blurred grey thumbnail that differ
    from the last frame judged moving. Comparing to the last *kept* frame, not the previous one,
    lets slow changes (daylight) accumulate until they count."""

    SIZE = (160, 120)
    PIXEL_DELTA = 25  # grey levels; above sensor noise once blurred

    def __init__(self, min_area_percent=0.5):
        self.min_area = min_area_percent / 100
        self.ref = None

    def moving(self, frame):
        small = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(frame, self.SIZE, interpolation=cv2.INTER_AREA),
                                              cv2.COLOR_BGR2GRAY), (5, 5), 0)
        if self.ref is not None:
            changed = np.count_nonzero(cv2.absdiff(small, self.ref) > self.PIXEL_DELTA) / small.size
            if changed < self.min_area:
                return False
        self.ref = small
        return True


def best_grid(n, width, height, aspect=4 / 3):
    """(rows, cols) that makes n tiles of the given aspect ratio as large as possible in width x height."""
    best, best_w = (1, 1), -1.0
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        tile_w = min(width / cols, height / rows * aspect)
        if tile_w > best_w + 1e-9:
            best, best_w = (rows, cols), tile_w
    return best


def compose_grid(frames, names=None, cell=(640, 480), adaptive=True):
    """Assemble frames into one image. Each cell is `cell` sized (swapped for portrait frames when
    adaptive), frames are letterboxed, never stretched. None frames give black cells."""
    n = len(frames)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    bw, bh = cell
    sizes = [(bh, bw) if adaptive and f is not None and f.shape[0] > f.shape[1] else (bw, bh) for f in frames]
    col_w = [max(sizes[i][0] for i in range(c, n, cols)) for c in range(cols)]
    row_h = [max(sizes[i][1] for i in range(r * cols, min(n, (r + 1) * cols))) for r in range(rows)]
    out = np.zeros((sum(row_h), sum(col_w), 3), np.uint8)
    for i, frame in enumerate(frames):
        r, c = divmod(i, cols)
        x, y, w, h = sum(col_w[:c]), sum(row_h[:r]), col_w[c], row_h[r]
        cell_img = out[y:y + h, x:x + w]
        if frame is not None:
            cell_img[:] = letterbox(frame, w, h)
        if names:
            draw_label(cell_img, names[i])
    return out


def safe_name(text):
    return re.sub(r"[^\w-]+", "_", text).strip("_") or "camera"


def imread(path):
    """cv2.imread counterpart of imwrite (non-ASCII paths). None if unreadable."""
    try:
        return cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return None


def imwrite(path, img):
    """cv2.imwrite silently fails on non-ASCII paths on Windows: encode in memory, write with numpy."""
    ok, buf = cv2.imencode(os.path.splitext(path)[1] or ".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if ok:
        buf.tofile(path)
    return ok
