"""Object detection on camera feeds (display only). Imported on first use: onnxruntime stays out of startup.

RF-DETR ONNX exports only for now; pre/post-processing mirrors RFDETR.predict() (port of
Plassys-Robot-Arm-Pic-IA/app/detector.py). Another model family = another adapter with the same
`num_classes`, `metadata` and `detect(frame_bgr, threshold)`."""
import json
import os
import shutil
import threading
import time

import cv2
import numpy as np

from imaging import smooth_rate

_MEAN = np.array([0.485, 0.456, 0.406], np.float32)  # ImageNet statistics RF-DETR normalises with
_STD = np.array([0.229, 0.224, 0.225], np.float32)
_INFERENCE = threading.Lock()  # one inference at a time across all models: CPU bounded like a single model


def postprocess(boxes, logits, threshold, size):
    """RF-DETR outputs -> (xyxy pixels, scores, class ids). boxes: (Q, 4) normalised cxcywh,
    logits: (Q, C + 1) with the background slot last, size: (w, h) of the analysed frame."""
    scores = 1 / (1 + np.exp(-np.clip(logits[:, :-1], -88, 88)))
    queries, classes = scores.shape
    flat = scores.reshape(-1)
    order = np.lexsort((np.arange(flat.size), -flat))[:queries]  # top-Q (query, class) pairs
    order = order[flat[order] > threshold]
    q, ids = np.divmod(order, classes)
    cx, cy, w, h = boxes[q].T
    xyxy = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1).astype(np.float32)
    xyxy *= np.array([size[0], size[1], size[0], size[1]], np.float32)
    return xyxy.reshape(-1, 4), flat[order], ids


class RfDetr:
    def __init__(self, model_bytes):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)  # leave cores to capture and encoding
        self.session = ort.InferenceSession(model_bytes, opts, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name, (self.height, self.width) = inp.name, inp.shape[2:]
        names = [o.name for o in self.session.get_outputs()]
        try:
            self._boxes = next(i for i, n in enumerate(names) if "dets" in n)
            self._logits = next(i for i, n in enumerate(names) if "labels" in n)
        except StopIteration:
            raise ValueError("not an RF-DETR ONNX model") from None
        self.num_classes = self.session.get_outputs()[self._logits].shape[-1] - 1
        self.metadata = self.session.get_modelmeta().custom_metadata_map

    def detect(self, frame_bgr, threshold):
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb.astype(np.float32) / 255, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
        tensor = ((resized - _MEAN) / _STD).transpose(2, 0, 1)[np.newaxis].astype(np.float32)
        out = self.session.run(None, {self.input_name: tensor})
        return postprocess(out[self._boxes][0], out[self._logits][0], threshold, (w, h))


def _as_list(value):
    """Class names from a JSON list, or a {"0": name} dict (Ultralytics style)."""
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        value = [value[k] for k in sorted(value, key=int)]
    return [str(v) for v in value]


def class_names(path, num_classes, metadata):
    """First source with the right count: ONNX metadata, classes.txt next to the model, <stem>.json,
    else class_0..class_N-1 (to be renamed in the settings)."""
    folder, stem = os.path.dirname(path), os.path.splitext(os.path.basename(path))[0]

    def candidates():
        for key in ("class_names", "names"):
            if key in metadata:
                yield lambda k=key: _as_list(metadata[k])
        yield lambda: [line.strip() for line in open(os.path.join(folder, "classes.txt"), encoding="utf-8") if line.strip()]
        yield lambda: _as_list(json.load(open(os.path.join(folder, stem + ".json"), encoding="utf-8")))

    for read in candidates():
        try:
            names = read()
        except (OSError, ValueError, TypeError, KeyError):
            continue
        if len(names) == num_classes:
            return names
    return [f"class_{i}" for i in range(num_classes)]


def import_model(src, models_dir, taken):
    """Check `src` loads as a supported model, copy it into models_dir; returns the library entry."""
    stem = os.path.splitext(os.path.basename(src))[0]
    try:
        with open(src, "rb") as f:
            model = RfDetr(f.read())
    except ValueError as e:
        raise ValueError(f"{stem}: {e}") from None
    except Exception as e:  # onnxruntime raises its own types for unreadable files
        raise ValueError(f"Cannot load {stem}: {e}") from None
    name, n = stem, 1
    while name in taken:
        n += 1
        name = f"{stem}_{n}"
    os.makedirs(models_dir, exist_ok=True)
    shutil.copyfile(src, os.path.join(models_dir, name + ".onnx"))
    return {"name": name, "file": name + ".onnx", "classes": class_names(src, model.num_classes, model.metadata),
            "threshold": 0.5}


class ModelWorker(threading.Thread):
    """One loaded model, serving its cameras in turn on their newest frame (CPU cost bounded per model).

    The GUI swaps `cameras` (a tuple) and `entry` (the library entry: classes and threshold are read at
    each detection, so edits apply live). Results are published on each camera as attribute swaps:
    `detections` = (xyxy, scores, names), `det_fps`, `det_status`."""

    def __init__(self, entry, models_dir):
        super().__init__(daemon=True)
        self.entry, self.models_dir = entry, models_dir
        self.cameras = ()
        self._halt = threading.Event()

    def stop(self):
        self._halt.set()

    def _status(self, text):
        for cam in self.cameras:
            cam.det_status = text

    def run(self):
        self._status("Loading model…")
        try:
            with open(os.path.join(self.models_dir, self.entry["file"]), "rb") as f:
                model = RfDetr(f.read())
        except FileNotFoundError:
            error = "Model not found"
        except Exception as e:
            error = f"Error: {e}"
        else:
            error = None
        if error:
            while not self._halt.wait(0.2):  # keep flagging cameras added later
                self._status(error)
            return
        done, last = {}, {}  # per camera: last frame_id analysed, time of its last result
        while not self._halt.is_set():
            busy = False
            for cam in self.cameras:
                frame, frame_id = cam.frame, cam.frame_id
                if frame is None or done.get(id(cam)) == frame_id:
                    continue
                busy = True
                done[id(cam)] = frame_id
                entry = self.entry
                try:
                    with _INFERENCE:
                        xyxy, scores, ids = model.detect(frame, entry["threshold"])
                except Exception as e:
                    cam.det_status = f"Error: {e}"
                    continue
                if not any(c is cam for c in self.cameras):  # removed meanwhile: leave its (cleared) results alone
                    continue
                classes = entry["classes"]
                names = [classes[i] if i < len(classes) else f"class_{i}" for i in ids]
                cam.detections = (xyxy, scores, names)
                now = time.perf_counter()
                if id(cam) in last:
                    cam.det_fps = smooth_rate(cam.det_fps, now - last[id(cam)], 0.2)
                last[id(cam)] = now
                cam.det_status = ""
            if not busy:
                self._halt.wait(0.01)
