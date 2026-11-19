import csv
import os
import sys
import threading

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from imaging import imwrite  # noqa: E402
from recorder import RenderJob, VideoRecorder  # noqa: E402
from recordings import TrackSource, find_tracks, load_times, renamed_path, session_label  # noqa: E402


def scripted_source(n_calls, moving):
    """Source returning a static image, except on calls where moving(i): a square that shifts."""
    calls, done = [0], threading.Event()

    def source():
        i = calls[0]
        calls[0] += 1
        if i >= n_calls:
            done.set()
            return []
        img = np.full((120, 160, 3), 90, np.uint8)
        x = 10 + (i % 5) * 25 if moving(i) else 10
        img[30:70, x:x + 40] = 250
        return [("dev0", "Cam A", img, i + 1)]
    return source, done


def test_motion_cut_and_parts(tmp_path):
    source, done = scripted_source(60, lambda i: 20 <= i < 40)
    rec = VideoRecorder(str(tmp_path), 60, True, source, None, motion=0.5, segment_minutes=10 / 3600)  # 10-frame parts
    rec.POST_ROLL = 0.05  # 3 frames
    rec.start()
    assert done.wait(10)
    rec.stop()
    assert rec.error is None
    # first frame (reference) + its post-roll, 20 moving frames + post-roll; the static rest is cut
    assert 20 <= rec.written <= 30 and rec.skipped >= 25, (rec.written, rec.skipped)
    tracks = find_tracks(str(tmp_path))
    kind, files = tracks["00_Cam_A"]
    assert kind == "video" and files[0] == "00_Cam_A_001.mp4" and len(files) == -(-rec.written // 10)
    src = TrackSource(str(tmp_path), kind, files)
    assert src.total == rec.written
    assert src.read(src.total - 1) is not None and src.locate(10) == ("00_Cam_A_002.mp4", 0)
    src.close()
    times, start = load_times(str(tmp_path))
    assert start is not None and sum(len(t) for t in times.values()) == rec.written
    with open(tmp_path / "frames.csv", newline="") as f:
        assert len(list(csv.reader(f))) == rec.written + 1


def test_single_file_when_not_split(tmp_path):
    source, done = scripted_source(30, lambda i: True)
    rec = VideoRecorder(str(tmp_path), 60, True, source, None, segment_minutes=None)
    rec.start()
    assert done.wait(10)
    rec.stop()
    assert rec.error is None and find_tracks(str(tmp_path))["00_Cam_A"][1] == ["00_Cam_A_001.mp4"]


def test_session_rename_keeps_prefix():
    path = os.path.join("out", "video_20261119_114751_155")
    renamed = renamed_path(path, '  Nuit: test 1/2 ')
    assert os.path.basename(renamed) == "video_20261119_114751_155 - Nuit test 1 2"
    assert session_label(renamed) == "Nuit test 1 2" and session_label(path) == ""
    assert renamed_path(renamed, "") == path  # empty label restores the original name


def test_resolution_tag():
    from camera import Camera
    cam = Camera("sim:0", "Sim", 0, (640, 480))
    assert cam.resolution_tag(np.zeros((480, 640, 3), np.uint8)) == ""  # native not probed yet
    cam.native = (1280, 720)
    assert cam.resolution_tag(np.zeros((480, 640, 3), np.uint8)) == "downscaled"
    assert cam.resolution_tag(np.zeros((720, 1280, 3), np.uint8)) == "native"
    assert cam.resolution_tag(np.zeros((1280, 720, 3), np.uint8)) == "native"  # rotated


def test_render_job(tmp_path):
    images = []
    for i in range(5):
        path = str(tmp_path / f"frame_{i + 1:06d}.jpg")
        imwrite(path, np.full((121, 161, 3), i * 40, np.uint8))  # odd size: must be made even for the encoder
        images.append(path)
    out = str(tmp_path / "render.mp4")
    job = RenderJob(images, out, 10)
    job.start()
    job.join(10)
    assert job.error is None and job.progress == 1
    src = TrackSource(str(tmp_path), "video", ["render.mp4"])
    assert src.total == 5
    src.close()


def test_resolution_choices_never_above_native():
    from camera import clamp, fits, resolution_choices
    choices = resolution_choices((1280, 720), (1280, 720))
    sizes = [r for r, _ in choices]
    assert (1280, 720) in sizes and (1920, 1080) not in sizes and (1024, 768) not in sizes  # 768 > 720
    assert [label for r, label in choices if r == (1280, 720)][0].endswith("native")
    odd = resolution_choices((2592, 1944), (2592, 1944))  # native not in the list: added, marked
    assert odd[-1] == ((2592, 1944), "2592×1944 · native")
    assert len(resolution_choices(None, (640, 480))) >= 8  # unknown native: no limit yet
    assert fits((720, 1280), (1280, 720)) and clamp((3840, 2160), (1280, 720)) == (1280, 720)
