"""Snapshots, timelapse (stills at an interval), video recording and timelapse rendering.

Every recording session gets its own folder with a frames.csv that tracks, per saved frame,
the timestamp and the source frame number of each camera (gaps = dropped or cut frames)."""
import csv
import os
import queue
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import cv2
import numpy as np
from PyQt5.QtCore import QTimer

from imaging import MotionDetector, draw_timestamp, imread, imwrite, letterbox, safe_name
from utils import print_error

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="save")


def save_async(path, make):
    """Build the image with make() and write it off the GUI thread."""
    def job():
        try:
            if not imwrite(path, make()):
                print_error(f"Could not write {path}")
        except Exception as e:
            print_error(f"Saving {path} failed: {e}")
    _pool.submit(job)


class FrameLog:
    """frames.csv: one row per camera per saved frame."""

    def __init__(self, folder):
        self.file = open(os.path.join(folder, "frames.csv"), "w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file)
        self.writer.writerow(["frame", "timestamp", "elapsed_s", "file", "camera", "camera_frame"])
        self.start = self.last_flush = time.perf_counter()

    def now(self):
        """(timestamp, elapsed) strings for a frame captured now."""
        return datetime.now().isoformat(timespec="milliseconds"), f"{time.perf_counter() - self.start:.3f}"

    def rows(self, n, entries, when=None):
        """entries: [(file, camera_label, camera_frame_id)]; `when` from now(), default: now."""
        ts, elapsed = when or self.now()
        self.writer.writerows([n, ts, elapsed, f, label, fid] for f, label, fid in entries)
        if time.perf_counter() - self.last_flush > 1:  # flushing every row costs too much over 24 h
            self.file.flush()
            self.last_flush = time.perf_counter()

    def close(self):
        self.file.close()


class Timelapse:
    """Saves the latest frames every `interval` seconds. `source()` returns
    [(device, label, frame, frame_id)], `compose(shots)` returns the grid image."""

    def __init__(self, folder, interval, per_camera, source, compose):
        os.makedirs(folder, exist_ok=True)
        self.folder, self.per_camera, self.source, self.compose = folder, per_camera, source, compose
        self.count = 0
        self.limit = 0  # auto-stop after this many seconds (0 = never), checked by the window
        self.started = time.perf_counter()
        self.log = FrameLog(folder)
        self.timer = QTimer()
        self.timer.timeout.connect(self.capture)
        self.timer.start(int(interval * 1000))
        self.capture()

    def remaining(self):
        return max(0, self.timer.remainingTime()) / 1000

    def elapsed(self):
        return time.perf_counter() - self.started

    def capture(self):
        shots = self.source()
        if not shots:
            return
        self.count += 1
        n = self.count
        if self.per_camera:
            entries = []
            for i, (_, label, frame, fid) in enumerate(shots):
                name = f"{i:02d}_{safe_name(label)}_{n:06d}.jpg"
                save_async(os.path.join(self.folder, name), lambda f=frame: f)
                entries.append((name, label, fid))
        else:
            name = f"frame_{n:06d}.jpg"
            save_async(os.path.join(self.folder, name), lambda s=shots: self.compose(s))
            entries = [(name, label, fid) for _, label, _, fid in shots]
        self.log.rows(n, entries)

    def stop(self):
        self.timer.stop()
        self.log.close()
        return self.count


class _Encoder:
    """One output video split into parts of `segment` frames: an unfinished mp4 is unreadable, so a
    crash or power cut loses at most the open part. Encodes in its own thread (cv2 releases the GIL),
    so files encode in parallel."""

    def __init__(self, folder, stem, fps, size, segment):
        self.folder, self.stem, self.fps, self.size, self.segment = folder, stem, fps, size, segment
        self.part = self.frames = 0
        self.error = None
        self.queue = queue.Queue(maxsize=8)  # ~0.25 s of buffer: bounded memory with many HD cameras
        first = self._open_next()
        self.thread = threading.Thread(target=self._run, args=(first,), daemon=True)
        self.thread.start()

    def _open_next(self):
        self.part += 1
        # shortcut: OpenCV's VideoWriter cannot open non-ASCII paths on Windows; keep the output folder ASCII
        for ext, codec in ((".mp4", "mp4v"), (".avi", "MJPG")):
            name = f"{self.stem}_{self.part:03d}{ext}"
            vw = cv2.VideoWriter(os.path.join(self.folder, name), cv2.VideoWriter_fourcc(*codec), self.fps, self.size)
            if vw.isOpened():
                self.file = name
                return vw
        raise RuntimeError(f"Cannot create a video file in {self.folder}")

    def push(self, frame):
        """Queue a frame (from the sampling thread). False if the encoder is behind: frame dropped."""
        if self.error:
            raise RuntimeError(self.error)
        if self.segment and self.frames and self.frames % self.segment == 0:
            self.queue.put(self._open_next(), timeout=10)  # a part switch must not be dropped
        try:
            self.queue.put_nowait(frame)
        except queue.Full:
            return False
        self.frames += 1
        return True

    def _run(self, writer):
        try:
            while (item := self.queue.get()) is not None:
                if isinstance(item, np.ndarray):
                    writer.write(letterbox(item, *self.size))  # size is fixed per file (rotation mid-recording)
                else:  # next part
                    writer.release()
                    writer = item
        except Exception as e:
            self.error = str(e)
        finally:
            writer.release()

    def close(self):
        if self.thread.is_alive():
            self.queue.put(None)
            self.thread.join()


class VideoRecorder(threading.Thread):
    """Samples the latest frames at a fixed fps and feeds one encoder per file (one per camera, or one
    grid video). With `motion` (min changed area, %), static stretches are cut: a stream is written only
    while it moves, plus POST_ROLL seconds. Frames an encoder cannot absorb are counted in `dropped`.
    `error` is set if it dies; it also stops itself before the disk is full."""

    POST_ROLL = 2.0  # seconds kept after motion stops, so short pauses don't make the video choppy
    MIN_FREE_BYTES = 1 << 30

    def __init__(self, folder, fps, per_camera, source, compose, motion=None, timestamp=False, segment_minutes=10):
        """segment_minutes=None: one single file per stream (unreadable if the recording is interrupted)."""
        super().__init__(daemon=True)
        os.makedirs(folder, exist_ok=True)
        self.folder, self.fps, self.per_camera, self.source, self.compose = folder, fps, per_camera, source, compose
        self.motion, self.timestamp = motion, timestamp
        self.segment = max(1, int(segment_minutes * 60 * fps)) if segment_minutes else None
        self.count = self.written = self.skipped = self.dropped = 0
        self.limit = 0  # auto-stop after this many seconds (0 = never), checked by the window
        self.error = None
        self.started = time.perf_counter()
        self._halt = threading.Event()

    def elapsed(self):
        return time.perf_counter() - self.started

    def stop(self):
        self._halt.set()
        self.join()
        return self.count

    def run(self):
        encoders, detectors, hold = {}, {}, {}
        log = FrameLog(self.folder)
        period, next_t, next_disk_check = 1 / self.fps, time.perf_counter(), 0
        post_roll = int(self.POST_ROLL * self.fps)
        try:
            while not self._halt.is_set():
                if time.perf_counter() > next_disk_check:
                    if shutil.disk_usage(self.folder).free < self.MIN_FREE_BYTES:
                        raise RuntimeError("Less than 1 GB free on the disk: recording stopped to keep the files safe.")
                    next_disk_check = time.perf_counter() + 10
                shots = self.source()
                if shots:
                    self.count += 1
                    when = log.now()
                    moving = None
                    if self.motion is not None:
                        moving = {dev for dev, _, frame, _ in shots
                                  if detectors.setdefault(dev, MotionDetector(self.motion)).moving(frame)}
                    if self.per_camera:
                        streams = [(shot[0], shot[1], [shot]) for shot in shots]
                    else:
                        streams = [("grid", "grid", shots)]
                    for key, label, group in streams:
                        if moving is not None:
                            if any(shot[0] in moving for shot in group):
                                hold[key] = post_roll
                            elif hold.get(key, 0) > 0:
                                hold[key] -= 1
                            else:
                                self.skipped += 1
                                continue
                        frame = group[0][2] if self.per_camera else self.compose(group)
                        if self.timestamp:  # camera frames are shared with the live view: draw on a copy
                            frame = draw_timestamp(frame.copy() if self.per_camera else frame,
                                                   when[0].replace("T", " "))
                        if key not in encoders:
                            h, w = frame.shape[:2]
                            encoders[key] = _Encoder(self.folder, f"{len(encoders):02d}_{safe_name(label)}",
                                                     self.fps, (w, h), self.segment)
                        enc = encoders[key]
                        if not enc.push(frame):
                            self.dropped += 1
                            continue
                        self.written += 1
                        log.rows(self.count, [(enc.file, cam, fid) for _, cam, _, fid in group], when)
                next_t += period
                delay = next_t - time.perf_counter()
                if delay < 0:  # late (file opening, slow compose): resync instead of bursting duplicate frames
                    next_t = time.perf_counter()
                self._halt.wait(max(0.0, delay))
        except Exception as e:
            self.error = str(e)
            print_error(f"Video recording stopped: {e}")
        finally:
            for enc in encoders.values():
                enc.close()
            log.close()


class RenderJob(threading.Thread):
    """Renders an image sequence (a timelapse) into a video in the background. `progress` goes 0..1."""

    def __init__(self, images, path, fps):
        super().__init__(daemon=True)
        self.images, self.path, self.fps = images, path, fps
        self.progress = 0.0
        self.error = None
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def run(self):
        vw, size = None, None
        try:
            for i, path in enumerate(self.images):
                if self._cancel.is_set():
                    break
                img = imread(path)
                if img is not None:
                    if vw is None:
                        h, w = img.shape[:2]
                        size = (w - w % 2, h - h % 2)
                        vw = cv2.VideoWriter(self.path, cv2.VideoWriter_fourcc(*"mp4v"), self.fps, size)
                        if not vw.isOpened():
                            raise RuntimeError(f"Cannot create {self.path}")
                    vw.write(letterbox(img, *size))
                self.progress = (i + 1) / len(self.images)
        except Exception as e:
            self.error = str(e)
        finally:
            if vw is not None:
                vw.release()
            if (self.error or self._cancel.is_set()) and os.path.exists(self.path):
                os.remove(self.path)  # never leave a half-rendered file behind
