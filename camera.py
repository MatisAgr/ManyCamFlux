"""Camera discovery and per-camera capture threads."""
import math
import re
import sys
import threading
import time

import cv2
import numpy as np
from PyQt5.QtGui import QImage
from PyQt5.QtMultimedia import QCameraInfo

from imaging import adjust, fit_size, resize, smooth_rate

# DirectShow opens fast and enumerates devices in the same order as Qt's camera list on Windows
BACKEND = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
RESOLUTIONS = [
    ((640, 480), "640×480 · VGA 4:3"),
    ((854, 480), "854×480 · FWVGA 16:9"),
    ((1024, 768), "1024×768 · XGA 4:3"),
    ((1280, 720), "1280×720 · HD 16:9"),
    ((1600, 1200), "1600×1200 · UXGA 4:3"),
    ((1920, 1080), "1920×1080 · Full HD 16:9"),
    ((3264, 2448), "3264×2448 · 8MP 4:3"),
    ((3840, 2160), "3840×2160 · 4K UHD 16:9"),
]


def fits(res, native):
    """True if res is not above native, whatever the orientation. Unknown native (None): everything fits."""
    if not native:
        return True
    (w, h), (nw, nh) = sorted(res, reverse=True), sorted(native, reverse=True)
    return w <= nw and h <= nh


def clamp(res, native):
    return tuple(res) if fits(res, native) else tuple(native)


def resolution_choices(native, current):
    """[(res, label)] a camera can really deliver: the list up to its native resolution (added and
    marked if missing), plus `current` if it is a custom one that fits."""
    choices = [(r, label) for r, label in RESOLUTIONS if fits(r, native)]
    for extra, label in ((native, "native"), (current, "custom")):
        if extra and fits(extra, native) and tuple(extra) not in [r for r, _ in choices]:
            choices.append((tuple(extra), f"{extra[0]}×{extra[1]} · {label}"))
    choices.sort(key=lambda c: c[0][0] * c[0][1])
    return [(r, f"{label} · native" if native and r == tuple(native) and "native" not in label else label)
            for r, label in choices]


SIMULATED = 0  # number of synthetic cameras added to the real ones (--simulate N); can change at runtime


def list_cameras():
    """Connected cameras as [(device_id, description, opencv_index)]. Cheap: safe to poll."""
    cams = []
    for pos, info in enumerate(QCameraInfo.availableCameras()):
        device = info.deviceName()
        m = re.search(r"/dev/video(\d+)$", device)  # Linux: the index is in the device path
        cams.append((device, info.description(), int(m.group(1)) if m else pos))
    return cams + [(f"sim:{i}", f"Simulated {i + 1}", i) for i in range(SIMULATED)]


class SimulatedCapture:
    """cv2.VideoCapture look-alike producing a 30 fps synthetic feed: a per-camera colour, a target
    moving 4 s out of 8, and the frame number, so dropped/duplicated/cut frames are visible in recordings."""

    NATIVE = (1920, 1080)  # behaves like a Full HD webcam: bigger requests get this

    def __init__(self, n, resolution, fps=30):
        w, h = resolution if resolution[0] * resolution[1] <= self.NATIVE[0] * self.NATIVE[1] else self.NATIVE
        self.n, self.period, self.count = n, 1 / fps, 0
        hsv = np.empty((h, w, 3), np.uint8)
        hsv[..., 0] = (n * 37) % 180
        hsv[..., 1] = 150
        hsv[..., 2] = np.linspace(70, 210, w, dtype=np.uint8)
        self.background = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        self.next = time.perf_counter()

    def isOpened(self):
        return True

    def release(self):
        pass

    def read(self):
        now = time.perf_counter()
        self.next = max(self.next + self.period, now - 1)  # never try to catch up more than 1 s
        time.sleep(max(0.0, self.next - now))
        self.count += 1
        frame = self.background.copy()
        h, w = frame.shape[:2]
        clock = self.count * self.period + 2 * self.n
        t = clock // 8 * 4 + min(clock % 8, 4)  # moves 4 s, then still 4 s: exercises the motion cut
        x = int(w / 2 + w / 3 * math.cos(t * (1 + 0.3 * self.n)))
        y = int(h / 2 + h / 3 * math.sin(t * 1.7))
        cv2.circle(frame, (x, y), h // 10, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.putText(frame, f"SIM {self.n + 1}  #{self.count}", (w // 30, h // 8), cv2.FONT_HERSHEY_SIMPLEX,
                    h / 400, (255, 255, 255), max(1, h // 240), cv2.LINE_AA)
        return True, frame


def open_capture(device, index, resolution, probe=False):
    """(capture or None, native resolution or None). probe=True also asks the camera for its largest
    mode first (~0.5-1.3 s with DirectShow, measured without fps impact), done once per camera."""
    if device.startswith("sim:"):
        return SimulatedCapture(index, resolution), SimulatedCapture.NATIVE
    cap = cv2.VideoCapture(index, BACKEND)
    if not cap.isOpened():
        cap.release()
        return None, None
    native = None
    if probe:  # an impossible size makes the driver fall back to its largest mode
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 10000)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 10000)
        native = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
    # MJPG lets USB webcams reach full frame rate at HD (measured 10 -> 30 fps at 720p).
    # Must come after the resolution: DirectShow ignores it otherwise.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    return cap, native


class Camera(threading.Thread):
    """One physical camera, grabbing and processing frames in its own thread.

    The GUI reads `frame`, `preview`, `frame_id`, `fps`, `status` and writes the settings
    attributes; each is a single attribute swap, atomic under the GIL, so no lock is needed.
    Never touch Qt widgets from here."""

    def __init__(self, device, description, index, resolution):
        super().__init__(daemon=True)
        self.device, self.description, self.index, self.resolution = device, description, index, resolution
        # settings (written by the GUI)
        self.label = description
        self.visible = True
        self.rotation = self.brightness = self.contrast = self.saturation = 0
        self.flip_h = self.flip_v = False
        self.keep_aspect = True
        self.display_size = (640, 360)  # device pixels of the widget showing this camera
        self.model = None  # vision model name (library entry) or None
        # output (written by this thread)
        self.frame = None    # latest processed full-resolution BGR frame
        self.preview = None  # (QImage, backing ndarray) sized for display_size
        self.frame_id = 0
        self.fps = 0.0
        self.native = None  # largest resolution the camera supports, once probed
        self.status = "Connecting…"
        # vision output (written by its vision.ModelWorker)
        self.detections = None  # (xyxy, scores, names) of the last analysed frame
        self.det_fps = 0.0
        self.det_status = ""
        self._reopen = False
        self._halt = threading.Event()

    def settings(self):
        return {"device": self.device, "name": self.label, "brightness": self.brightness,
                "contrast": self.contrast, "saturation": self.saturation,
                "rotation_angle": self.rotation, "flip_horizontal": self.flip_h,
                "flip_vertical": self.flip_v, "visible": self.visible, "resolution": list(self.resolution), "model": self.model}

    def apply_settings(self, s):
        self.label = str(s.get("name", self.label))
        self.brightness = int(s.get("brightness", 0))
        self.contrast = int(s.get("contrast", 0))
        self.saturation = int(s.get("saturation", 0))
        self.rotation = int(s.get("rotation_angle", 0)) % 360
        self.flip_h = bool(s.get("flip_horizontal", False))
        self.flip_v = bool(s.get("flip_vertical", False))
        self.visible = bool(s.get("visible", True))
        self.model = s["model"] if isinstance(s.get("model"), str) else None
        if isinstance(s.get("resolution"), list) and len(s["resolution"]) == 2:
            self.resolution = tuple(int(v) for v in s["resolution"])

    def resolution_tag(self, frame):
        """'native', 'downscaled' (the camera can do more) or '' if unknown. Rotation-proof."""
        if self.native is None or frame is None:
            return ""
        got, best = sorted(frame.shape[:2]), sorted(self.native[::-1])
        return "native" if all(g >= b for g, b in zip(got, best)) else "downscaled"

    def reopen(self, resolution):
        self.resolution = resolution
        self._reopen = True

    def stop(self):
        self._halt.set()

    def run(self):
        cap, fails, last = None, 0, time.perf_counter()
        while not self._halt.is_set():
            if cap is None or self._reopen:
                self._reopen = False
                if cap is not None:
                    cap.release()
                self.status = "Connecting…"
                cap, native = open_capture(self.device, self.index, self.resolution, probe=self.native is None)
                if native and native[0] > 0:
                    self.native = native
                if cap is None:
                    self.status = "No signal"
                    self._halt.wait(2)
                    continue
                fails = 0
            ok, raw = cap.read()
            if not ok:
                fails += 1
                if fails >= 50:  # ~2.5 s without a frame: drop the handle and reopen
                    self.status = "No signal"
                    cap.release()
                    cap = None
                self._halt.wait(0.05)
                continue
            fails = 0
            frame = adjust(raw, self.rotation, self.brightness, self.contrast, self.saturation,
                           self.flip_h, self.flip_v)
            now = time.perf_counter()
            self.fps = smooth_rate(self.fps, now - last)
            last = now
            self.preview = self._make_preview(frame)
            self.frame = frame
            self.frame_id += 1
            self.status = ""
        if cap is not None:
            cap.release()

    def _make_preview(self, frame):
        dw, dh = self.display_size
        h, w = frame.shape[:2]
        tw, th = fit_size(w, h, dw, dh) if self.keep_aspect else (dw, dh)
        small = resize(frame, tw, th)
        return QImage(small.data, tw, th, small.strides[0], QImage.Format_BGR888), small
