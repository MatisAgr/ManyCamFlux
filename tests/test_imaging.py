import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from imaging import MotionDetector, adjust, best_grid, compose_grid, fit_size, imwrite, letterbox, smooth_rate  # noqa: E402


def frame(w, h, value=128):
    return np.full((h, w, 3), value, np.uint8)


def test_best_grid():
    assert best_grid(1, 800, 600) == (1, 1)
    assert best_grid(4, 1600, 900, 16 / 9) == (2, 2)
    assert best_grid(3, 3000, 600, 4 / 3) == (1, 3)   # very wide window: one row
    assert best_grid(2, 400, 1200, 4 / 3) == (2, 1)   # tall window: one column


def test_fit_and_letterbox():
    assert fit_size(1920, 1080, 640, 640) == (640, 360)
    out = letterbox(frame(1920, 1080, 200), 640, 640)
    assert out.shape == (640, 640, 3)
    assert out[0, 0].sum() == 0 and out[320, 320, 0] == 200  # black bars, image centred


def test_adjust():
    f = frame(640, 480)
    assert adjust(f, rotation=90).shape == (640, 480, 3)
    assert adjust(f) is f  # nothing to do: no copy
    assert adjust(f, brightness=50)[0, 0, 0] == 178
    assert (adjust(f, saturation=50) == f).all()  # grey has no saturation


def test_flip():
    f = frame(4, 2)
    f[0, 0] = 255
    assert adjust(f, flip_h=True)[0, 3, 0] == 255
    assert adjust(f, flip_v=True)[1, 0, 0] == 255
    assert adjust(f, flip_h=True, flip_v=True)[1, 3, 0] == 255
    assert adjust(f, rotation=90, flip_v=True).shape == (4, 2, 3)  # flip applies to the rotated image


def test_motion_detector():
    rng = np.random.default_rng(0)
    still = frame(320, 240, 100)
    det = MotionDetector(0.5)
    assert det.moving(still)  # first frame is the reference
    for _ in range(5):  # sensor noise is not motion
        noisy = np.clip(still.astype(int) + rng.integers(-8, 9, still.shape), 0, 255).astype(np.uint8)
        assert not det.moving(noisy)
    moved = still.copy()
    moved[50:110, 50:110] = 255
    assert det.moving(moved)
    assert det.moving(still)  # square gone: that is a change too, and still becomes the reference again
    drift =[det.moving(frame(320, 240, 100 + i)) for i in range(1, 40)]  # slow light change accumulates
    assert not drift[0] and any(drift)


def test_compose_grid_adaptive():
    landscape, portrait = frame(640, 480), frame(480, 640)
    assert compose_grid([landscape, landscape], cell=(640, 480)).shape == (480, 1280, 3)
    assert compose_grid([landscape, portrait], cell=(640, 480)).shape == (640, 1120, 3)
    assert compose_grid([landscape, portrait], cell=(640, 480), adaptive=False).shape == (480, 1280, 3)
    assert compose_grid([landscape, None, landscape], names=["a", "b", "c"]).shape == (960, 1280, 3)


def test_imwrite_unicode_path(tmp_path):
    path = os.path.join(tmp_path, "caméra é.jpg")
    assert imwrite(path, frame(64, 48))
    assert cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR).shape == (48, 64, 3)


def test_parse_hms():
    from utils import hms, parse_hms
    assert parse_hms("01:30:05") == 5405 and parse_hms("26:00:00") == 93600  # more than 24 h is fine
    assert parse_hms("10:00") == 600 and parse_hms("45") == 45
    assert parse_hms("") == 0 and parse_hms("1:x") == 0 and parse_hms("1:2:3:4") == 0
    assert hms(93600) == "26:00:00"


def test_smooth_rate_is_not_inflated_by_jitter():
    rate = 0.0
    for i in range(400):  # irregular frames, 30 per second on average (a loaded CPU)
        rate = smooth_rate(rate, 0.010 if i % 2 else 0.0567)
    assert 28 < rate < 32, rate  # averaging 1/interval gave ~60
    assert smooth_rate(0.0, 0.5) == 2.0  # first interval: taken as is
