import os
import subprocess
import sys
import time
import types

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import vision  # noqa: E402
from vision import RfDetr, class_names, import_model, postprocess  # noqa: E402

MODEL = os.path.join(ROOT, ".proj", "model.onnx")  # RF-DETR export, 2 classes (gitignored)
needs_model = pytest.mark.skipif(not os.path.exists(MODEL), reason="no test model in .proj/")


def wait_for(cond, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.05)
    assert cond(), "condition not met in time"


def fake_cam():
    return types.SimpleNamespace(frame=np.zeros((480, 640, 3), np.uint8), frame_id=1, ping=None,
                                 detections=None, det_fps=0.0, det_status="")


def test_onnxruntime_loads_after_pyqt():
    # PyQt5 ships an old msvcp140.dll; the app entry point must preload the system one first
    code = "import ManyCamFlux, PyQt5.QtWidgets, PyQt5.QtMultimedia, onnxruntime"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-300:]


def test_postprocess_threshold_and_boxes():
    boxes = np.array([[0.5, 0.5, 0.2, 0.4], [0.1, 0.1, 0.1, 0.1]], np.float32)
    logits = np.array([[-9, 4, -9], [-9, -9, -9]], np.float32)  # query 0 -> class 1; last slot = background
    xyxy, scores, ids = postprocess(boxes, logits, 0.5, (200, 100))
    assert ids.tolist() == [1] and scores[0] > 0.98
    np.testing.assert_allclose(xyxy[0], [80, 30, 120, 70], atol=1e-4)


def test_postprocess_nothing():
    assert len(postprocess(np.zeros((3, 4), np.float32), np.full((3, 3), -9, np.float32), 0.5, (10, 10))[0]) == 0


def test_class_names_order(tmp_path):
    model = str(tmp_path / "m.onnx")
    (tmp_path / "m.onnx").write_bytes(b"")
    assert class_names(model, 2, {}) == ["class_0", "class_1"]
    (tmp_path / "m.json").write_text('["x", "y"]')
    assert class_names(model, 2, {}) == ["x", "y"]
    (tmp_path / "classes.txt").write_text("arm\nholder\n")
    assert class_names(model, 2, {}) == ["arm", "holder"]
    assert class_names(model, 2, {"class_names": '["a", "b"]'}) == ["a", "b"]  # metadata wins
    assert class_names(model, 3, {"class_names": '["a", "b"]'}) == ["class_0", "class_1", "class_2"]  # wrong counts skipped


def test_import_rejects_non_model(tmp_path):
    bad = tmp_path / "x.onnx"
    bad.write_bytes(b"not onnx")
    with pytest.raises(ValueError):
        import_model(str(bad), str(tmp_path / "models"), [])


@needs_model
def test_rfdetr_real_model(tmp_path):
    det = RfDetr(open(MODEL, "rb").read())
    assert det.num_classes == 2
    xyxy, scores, ids = det.detect(np.zeros((480, 640, 3), np.uint8), 0.5)
    assert xyxy.shape[1] == 4 and len(scores) == len(ids)
    entry = import_model(MODEL, str(tmp_path), taken=["model"])
    assert entry["name"] == "model_2" and entry["threshold"] == 0.5 and len(entry["classes"]) == 2
    assert (tmp_path / entry["file"]).exists()


def test_worker_missing_file(tmp_path):
    cam = fake_cam()
    w = vision.ModelWorker({"name": "x", "file": "x.onnx", "classes": [], "threshold": 0.5}, str(tmp_path))
    w.cameras = (cam,)
    w.start()
    wait_for(lambda: cam.det_status == "Model not found")
    late = fake_cam()  # a camera added after the failure gets the status too
    w.cameras = (cam, late)
    wait_for(lambda: late.det_status == "Model not found")
    w.stop()
    w.join(2)
    assert not w.is_alive()


@needs_model
def test_worker_serves_all_cameras(tmp_path):
    entry = import_model(MODEL, str(tmp_path), [])
    entry["classes"] = ["arm", "holder"]
    a, b = fake_cam(), fake_cam()
    w = vision.ModelWorker(entry, str(tmp_path))
    w.cameras = (a, b)
    w.start()
    wait_for(lambda: a.detections is not None and b.detections is not None and a.det_status == "")
    xyxy, scores, names = a.detections
    assert len(xyxy) == len(scores) == len(names)
    for _ in range(3):  # new frames only: det_fps needs two results of the same camera
        a.frame_id += 1
        time.sleep(0.3)
    wait_for(lambda: a.det_fps > 0)
    w.stop()
    w.join(2)
    assert not w.is_alive()


def test_inference_is_one_at_a_time_across_models(tmp_path, monkeypatch):
    # CPU bound like a single model, whatever the number of models in use
    state = {"now": 0, "max": 0}

    class Slow:
        def __init__(self, data):
            pass

        def detect(self, frame, threshold):
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
            time.sleep(0.02)
            state["now"] -= 1
            return np.zeros((0, 4), np.float32), np.zeros(0, np.float32), np.zeros(0, int)

    monkeypatch.setattr(vision, "RfDetr", Slow)
    (tmp_path / "m.onnx").write_bytes(b"x")
    workers, cams = [], []
    for _ in range(3):
        cam = fake_cam()
        w = vision.ModelWorker({"name": "m", "file": "m.onnx", "classes": [], "threshold": 0.5}, str(tmp_path))
        w.cameras = (cam,)
        w.start()
        workers.append(w)
        cams.append(cam)
    for _ in range(10):
        for cam in cams:
            cam.frame_id += 1
        time.sleep(0.03)
    for w in workers:
        w.stop()
        w.join(2)
    assert state["max"] == 1


@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_feed_refresh_with_new_detections_same_frame(qapp):
    from PyQt5.QtWidgets import QWidget
    from camera_widgets import CamFeedWidget
    cam = fake_cam()
    cam.status, cam.label, cam.model = "", "cam", "m"
    parent = QWidget()  # keep a reference: Qt deletes the child with it
    feed = CamFeedWidget(cam, types.SimpleNamespace(recording=lambda cam: False, selected=None), parent)
    cam.detections = (np.zeros((1, 4), np.float32), np.ones(1, np.float32), ["a"])
    feed.refresh()
    cam.detections = (np.zeros((2, 4), np.float32), np.ones(2, np.float32), ["a", "b"])  # same frame_id
    feed.refresh()  # raised "truth value of an array is ambiguous" in the 33 ms timer


def test_panel_shows_and_clears_a_missing_model(qapp):
    from dialogs import CameraPanel
    calls = []
    main = types.SimpleNamespace(cfg={"models": []}, feeds={}, select_camera=lambda c: None,
                                 set_camera_model=lambda cam, name: calls.append(name),
                                 save_config=print, import_config=print, set_visible=print, rotate=print,
                                 set_flip=print, set_camera_resolution=print, set_camera_fps=print)
    panel = CameraPanel(main)
    cam = types.SimpleNamespace(model="gone", device="d", label="c", native=None, resolution=(640, 480),
                                visible=True, flip_h=False, flip_v=False, brightness=0, contrast=0,
                                saturation=0, rotation=0, max_fps=0)
    panel.set_camera(cam)
    combo = panel.model_combo
    assert combo.currentData() == "gone" and "missing" in combo.currentText()
    combo.setCurrentIndex(combo.findData(None))
    assert calls == [None]


def test_vision_strip_shows_count_and_best_score_per_class(qapp):
    from PyQt5.QtWidgets import QWidget
    from camera_widgets import CamFeedWidget
    cam = fake_cam()
    cam.status, cam.label, cam.model, cam.det_fps = "", "cam", "m", 3.0
    parent = QWidget()
    feed = CamFeedWidget(cam, types.SimpleNamespace(recording=lambda cam: False, selected=None), parent)
    cam.detections = (np.zeros((3, 4), np.float32), np.array([0.78, 0.95, 0.91], np.float32),
                      ["arm", "holder", "arm"])
    assert feed._vision_text() == "m · 3.0 det/s · arm ×2 (0.91), holder ×1 (0.95)"


def test_settings_rename_model(qapp, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QMessageBox
    from camera_widgets import DEFAULTS
    from dialogs import CaptureSettingsDialog
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))
    cfg = dict(DEFAULTS, models=[{"name": "a", "file": "a.onnx", "classes": ["x"], "threshold": 0.5},
                                 {"name": "b", "file": "b.onnx", "classes": ["y"], "threshold": 0.5}])
    d = CaptureSettingsDialog(cfg, None, str(tmp_path))
    d.model_list.setCurrentRow(0)
    d.model_name.setText("b")  # taken: refused
    d.model_name.editingFinished.emit()
    assert warnings and d.values()["models"][0]["name"] == "a" and d.model_name.text() == "a"
    d.model_name.setText("  arm detector ")
    d.model_name.editingFinished.emit()
    assert d.values()["models"][0]["name"] == "arm detector"
    assert d.model_list.item(0).text() == "arm detector"
    assert d.renamed() == {"a": "arm detector"}
    assert cfg["models"][0]["name"] == "a"  # the dialog edits a copy until OK
