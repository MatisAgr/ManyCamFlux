"""Recordings browser: lists the session folders, plays videos (all parts as one timeline) and
timelapse image sequences, shows the real capture time of each frame (from frames.csv), and
renders a timelapse into a video."""
import bisect
import csv
import os
import re
import threading
from array import array
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import accumulate

import cv2
from PyQt5.QtCore import QFile, QRect, QSize, Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QIcon, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                             QListWidgetItem, QMenu, QMessageBox, QPushButton, QSlider, QSpinBox, QSplitter,
                             QToolButton, QVBoxLayout, QWidget)

from imaging import fit_size, imread, resize, safe_name
from utils import hms, icon

# session folders: <kind>_<date>_<ms>, optionally followed by " - <label>" once renamed
SESSION_RE = re.compile(r"^(video|timelapse)_(\d{8}_\d{6})(?:_\d{3})?")
LABEL_SEP = " - "
VIDEO_RE = re.compile(r"^(.*?)(?:_(\d{3}))?\.(mp4|avi)$", re.I)  # parts: <stem>_001.mp4, <stem>_002.mp4...
IMAGE_RE = re.compile(r"^(.*)_(\d{6})\.jpg$", re.I)
SPEEDS = [1, 2, 4, 8, 16, 64]
IMAGE_FPS = 10  # playback speed of timelapse images


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def session_label(path):
    """The user label of a renamed session folder, '' if none."""
    name = os.path.basename(path)
    m = SESSION_RE.match(name)
    return name[m.end():].strip().removeprefix(LABEL_SEP.strip()).strip() if m else ""


def renamed_path(path, label):
    """Folder path for a new label, keeping the '<kind>_<date>_<ms>' prefix the browser relies on.
    An empty label restores the original name."""
    name = os.path.basename(path)
    prefix = SESSION_RE.match(name).group(0)
    label = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', " ", label).strip().rstrip(".")  # Windows-forbidden characters
    return os.path.join(os.path.dirname(path), prefix + (LABEL_SEP + label if label else ""))


def to_trash(path):
    """Move a file or folder to the system trash / recycle bin (recoverable). True on success."""
    result = QFile.moveToTrash(path)
    return result[0] if isinstance(result, tuple) else bool(result)


def scan_sessions(root):
    """[(path, kind, datetime, size_bytes)], newest first."""
    sessions = []
    if os.path.isdir(root):
        for entry in os.scandir(root):
            m = SESSION_RE.match(entry.name)
            if entry.is_dir() and m:
                size = sum(f.stat().st_size for f in os.scandir(entry.path) if f.is_file())
                sessions.append((entry.path, m.group(1), datetime.strptime(m.group(2), "%Y%m%d_%H%M%S"), size))
    return sorted(sessions, key=lambda s: s[2], reverse=True)


def find_tracks(folder):
    """{track name: (kind, [file names])}: video parts grouped by stem, image sequences by prefix."""
    videos, images = defaultdict(list), defaultdict(list)
    if not os.path.isdir(folder):  # deleted meanwhile
        return {}
    for name in sorted(os.listdir(folder)):
        if m := VIDEO_RE.match(name):
            videos[m.group(1)].append(name)
        elif m := IMAGE_RE.match(name):
            images[m.group(1)].append(name)
    tracks = {k: ("video", v) for k, v in videos.items()}
    tracks.update({f"{k} (images)": ("images", v) for k, v in images.items()})
    return tracks


def load_times(folder):
    """frames.csv -> ({file: elapsed seconds of each frame written to it}, session start).
    Kept as compact float arrays: a 24 h multi-camera log has millions of rows."""
    times, last, start = defaultdict(lambda: array("d")), {}, None
    try:
        with open(os.path.join(folder, "frames.csv"), newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) < 4:
                    continue
                frame, ts, elapsed, file = row[:4]
                if last.get(file) == frame:  # grid videos: one row per camera for the same frame
                    continue
                last[file] = frame
                times[file].append(float(elapsed))
                if start is None:
                    start = datetime.fromisoformat(ts) - timedelta(seconds=float(elapsed))
    except (OSError, ValueError):
        pass
    return dict(times), start


def to_qimage(frame):
    return QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format_BGR888).copy()


class TrackSource:
    """Random access to a track's frames: video parts played as one timeline, or an image sequence."""

    def __init__(self, folder, kind, files):
        self.kind, self.files = kind, files
        self.paths = [os.path.join(folder, f) for f in files]
        self.fps = IMAGE_FPS
        if kind == "video":
            counts, fps = [], 0
            for p in self.paths:
                cap = cv2.VideoCapture(p)
                counts.append(max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT))))
                fps = fps or cap.get(cv2.CAP_PROP_FPS)
                cap.release()
            self.fps = fps or 30
        else:
            counts = [1] * len(files)
        self.starts = list(accumulate([0] + counts))[:-1]
        self.total = sum(counts)
        self.cap, self.cap_part, self.pos = None, -1, -1

    def locate(self, i):
        """(file name, frame index inside that file)"""
        part = bisect.bisect_right(self.starts, i) - 1
        return self.files[part], i - self.starts[part]

    def read(self, i):
        part = bisect.bisect_right(self.starts, i) - 1
        if self.kind == "images":
            return imread(self.paths[part])
        k = i - self.starts[part]
        if part != self.cap_part:
            self.close()
            self.cap, self.cap_part = cv2.VideoCapture(self.paths[part]), part
        if 0 < k - self.pos <= 8:  # short skip (fast play): grabbing beats seeking
            for _ in range(k - self.pos - 1):
                self.cap.grab()
        elif k != self.pos + 1:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, k)
        ok, frame = self.cap.read()
        self.pos = k
        return frame if ok else None

    def close(self):
        if self.cap is not None:
            self.cap.release()
        self.cap, self.cap_part, self.pos = None, -1, -1


class FrameView(QWidget):
    def __init__(self):
        super().__init__()
        self.image = None
        self.setMinimumSize(320, 180)

    def set_frame(self, frame):
        self.image = to_qimage(frame) if frame is not None else None
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(16, 17, 19))
        if self.image is not None:
            w, h = fit_size(self.image.width(), self.image.height(), self.width(), self.height())
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(QRect((self.width() - w) // 2, (self.height() - h) // 2, w, h), self.image)


class RecordingsDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Recordings")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint)
        self.resize(1200, 740)
        self.source = None
        self.folder = None
        self.pos = 0
        self.playing = False
        self.times = None  # (folder, times, start) once frames.csv is loaded
        self._thumbs = []

        self.list = QListWidget()
        self.list.setIconSize(QSize(128, 72))
        self.list.setSpacing(2)
        self.list.currentRowChanged.connect(self.open_session)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._session_menu)
        refresh = QPushButton(icon("rotate-right"), " Refresh")
        refresh.clicked.connect(self.refresh)
        self.rename_btn = QPushButton(icon("edit"), " Rename")
        self.rename_btn.setToolTip("Rename this recording (F2)")
        self.rename_btn.clicked.connect(self.rename_session)
        self.delete_btn = QPushButton(icon("trash"), " Delete")
        self.delete_btn.setToolTip("Move this recording to the recycle bin (Del)")
        self.delete_btn.clicked.connect(self.delete_session)
        list_buttons = QHBoxLayout()
        for b in (refresh, self.rename_btn, self.delete_btn):
            list_buttons.addWidget(b)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.list)
        lv.addLayout(list_buttons)

        self.title = QLabel()
        self.track = QComboBox()
        self.track.currentIndexChanged.connect(self.open_track)
        top = QHBoxLayout()
        top.addWidget(self.title, 1)
        top.addWidget(QLabel("Track"))
        top.addWidget(self.track)
        self.delete_track_btn = QToolButton()
        self.delete_track_btn.setIcon(icon("trash"))
        self.delete_track_btn.setToolTip("Move only this track (camera video or image sequence) to the recycle bin")
        self.delete_track_btn.clicked.connect(self.delete_track)
        top.addWidget(self.delete_track_btn)

        self.view = FrameView()
        self.play_btn = QToolButton()
        self.play_btn.setIcon(icon("play"))
        self.play_btn.setIconSize(QSize(22, 22))
        self.play_btn.setToolTip("Play / pause (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.valueChanged.connect(self.show_frame)
        self.speed = QComboBox()
        self.speed.addItems([f"×{s}" for s in SPEEDS])
        self.speed.setToolTip("Playback speed")
        self.speed.currentIndexChanged.connect(self._restart_timer)
        controls = QHBoxLayout()
        controls.addWidget(self.play_btn)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.speed)
        self.info = QLabel()
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)

        folder_btn = QPushButton(icon("folder"), " Open folder")
        folder_btn.clicked.connect(lambda: self.folder and QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder)))
        self.external_btn = QPushButton(icon("library"), " Open in system player")
        self.external_btn.clicked.connect(self.open_external)
        self.render_fps = QSpinBox()
        self.render_fps.setRange(1, 60)
        self.render_fps.setValue(24)
        self.render_fps.setSuffix(" fps")
        self.render_btn = QPushButton(icon("record"), " Render to video")
        self.render_btn.setToolTip("Turn this image sequence into a video (progress at the bottom of the main window)")
        self.render_btn.clicked.connect(self.render)
        actions = QHBoxLayout()
        actions.addWidget(folder_btn)
        actions.addWidget(self.external_btn)
        actions.addStretch(1)
        actions.addWidget(self.render_fps)
        actions.addWidget(self.render_btn)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addLayout(top)
        rv.addWidget(self.view, 1)
        rv.addLayout(controls)
        rv.addWidget(self.info)
        rv.addLayout(actions)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([320, 880])
        QVBoxLayout(self).addWidget(split)
        self.timer = QTimer(self, timeout=self._advance)

    # ---------- sessions ----------
    def refresh(self):
        self.pause()
        self._thumbs = []
        self.list.blockSignals(True)
        self.list.clear()
        busy = {r.folder for r in (self.main.video, self.main.timelapse) if r is not None}
        for path, kind, date, size in scan_sessions(self.main.output_dir("")):
            live = "  ● recording" if path in busy else ""
            label = session_label(path)
            title = f"{label}\n{kind.capitalize()} · " if label else f"{kind.capitalize()}{live}\n"
            item = QListWidgetItem(f"{title}{date:%Y-%m-%d %H:%M:%S}\n{human_size(size)}")
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            self.list.addItem(item)
            self._thumbs.append(item)
        self.list.blockSignals(False)
        QTimer.singleShot(0, self._next_thumb)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.open_session(-1)

    def _next_thumb(self):
        """One thumbnail per event-loop pass, so a long list never freezes the window."""
        if not self._thumbs:
            return
        item = self._thumbs.pop(0)
        folder = item.data(Qt.UserRole)
        tracks = find_tracks(folder)
        if tracks:
            kind, files = next(iter(tracks.values()))
            src = TrackSource(folder, kind, files[:1])
            frame = src.read(0) if src.total else None
            src.close()
            if frame is not None:
                w, h = fit_size(frame.shape[1], frame.shape[0], 128, 72)
                item.setIcon(QIcon(QPixmap.fromImage(to_qimage(resize(frame, w, h)))))
        QTimer.singleShot(0, self._next_thumb)

    def open_session(self, row):
        self.pause()
        self.folder = self.list.item(row).data(Qt.UserRole) if row >= 0 else None
        self.title.setText(f"<b>{os.path.basename(self.folder)}</b>" if self.folder else "No recording yet")
        for b in (self.rename_btn, self.delete_btn):
            b.setEnabled(self.folder is not None)
        self.track.blockSignals(True)
        self.track.clear()
        self.tracks = find_tracks(self.folder) if self.folder else {}
        for name, (kind, files) in self.tracks.items():
            parts = f" · {len(files)} parts" if kind == "video" and len(files) > 1 else ""
            self.track.addItem(f"{name}{parts}", name)
        self.track.blockSignals(False)
        if self.folder:
            folder = self.folder
            threading.Thread(target=lambda: setattr(self, "times", (folder, *load_times(folder))), daemon=True).start()
        self.open_track(0)

    def open_track(self, index):
        self.pause()
        if self.source:
            self.source.close()
        self.source = None
        name = self.track.itemData(index)
        if name is not None:
            kind, files = self.tracks[name]
            self.source = TrackSource(self.folder, kind, files)
        ok = self.source is not None and self.source.total > 0
        for w in (self.play_btn, self.slider, self.speed):
            w.setEnabled(ok)
        self.external_btn.setEnabled(ok and self.source.kind == "video")
        self.delete_track_btn.setEnabled(name is not None)
        self.render_btn.setEnabled(ok and self.source.kind == "images")
        self.render_fps.setEnabled(self.render_btn.isEnabled())
        if not ok:
            self.view.set_frame(None)
            self.info.setText("Nothing to play here (a file still being recorded is readable once its part is closed)."
                              if self.folder else "")
            return
        self.slider.blockSignals(True)
        self.slider.setRange(0, self.source.total - 1)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.show_frame(0)

    # ---------- playback ----------
    def show_frame(self, i):
        if not self.source:
            return
        self.pos = i
        self.view.set_frame(self.source.read(i))
        if self.slider.value() != i:
            self.slider.blockSignals(True)
            self.slider.setValue(i)
            self.slider.blockSignals(False)
        self._update_info()

    def _update_info(self):
        src = self.source
        text = f"{hms(self.pos / src.fps)} / {hms(src.total / src.fps)}  ·  frame {self.pos + 1} / {src.total}"
        times = self.times
        if times is None or times[0] != self.folder:
            text += "  ·  reading timestamps…"
        else:
            file, k = src.locate(self.pos)
            elapsed, start = times[1].get(file), times[2]
            if elapsed is not None and k < len(elapsed) and start is not None:
                text += f"  ·  recorded {(start + timedelta(seconds=elapsed[k])):%Y-%m-%d %H:%M:%S}"
        self.info.setText(text)

    def toggle_play(self):
        if self.playing:
            self.pause()
        elif self.source:
            if self.pos >= self.source.total - 1:
                self.show_frame(0)
            self.playing = True
            self.play_btn.setIcon(icon("pause"))
            self._restart_timer()

    def pause(self):
        self.playing = False
        self.timer.stop()
        self.play_btn.setIcon(icon("play"))

    def _rate(self):
        """(frames advanced per tick, tick ms): at most ~30 displayed frames/s, skipping frames when faster."""
        frames_per_s = self.source.fps * SPEEDS[self.speed.currentIndex()]
        step = max(1, round(frames_per_s / 30))
        return step, max(1, int(1000 * step / frames_per_s))

    def _restart_timer(self):
        if self.playing and self.source:
            self.timer.start(self._rate()[1])

    def _advance(self):
        step, _ = self._rate()
        nxt = self.pos + step
        if nxt >= self.source.total:
            self.show_frame(self.source.total - 1)
            self.pause()
        else:
            self.show_frame(nxt)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Space:
            self.toggle_play()
        elif key == Qt.Key_F2:
            self.rename_session()
        elif key == Qt.Key_Delete:
            self.delete_session()
        elif key in (Qt.Key_Left, Qt.Key_Right) and self.source:
            self.pause()
            self.show_frame(min(max(0, self.pos + (1 if key == Qt.Key_Right else -1)), self.source.total - 1))
        else:
            super().keyPressEvent(event)

    # ---------- actions ----------
    def _session_menu(self, pos):
        if self.list.itemAt(pos) is None:
            return
        menu = QMenu(self)
        menu.addAction(icon("edit"), "Rename…", self.rename_session)
        menu.addAction(icon("folder"), "Open folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder)))
        menu.addSeparator()
        menu.addAction(icon("trash"), "Delete…", self.delete_session)
        menu.exec_(self.list.mapToGlobal(pos))

    def _busy(self):
        """True (and tells the user) if the selected session is still being recorded."""
        busy = {r.folder for r in (self.main.video, self.main.timelapse) if r is not None}
        if self.folder in busy:
            QMessageBox.information(self, "Recordings", "This recording is still running: stop it first.")
            return True
        return False

    def _release(self):
        """Close the open file: Windows refuses to rename or delete a file in use."""
        self.pause()
        if self.source:
            self.source.close()

    def _select_path(self, path):
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.UserRole) == path:
                self.list.setCurrentRow(row)

    def rename_session(self):
        if not self.folder or self._busy():
            return
        label, ok = QInputDialog.getText(self, "Rename recording",
                                         "Name (the date stays in the folder name, empty = original name):",
                                         text=session_label(self.folder))
        if not ok:
            return
        new = renamed_path(self.folder, label)
        if new == self.folder:
            return
        if os.path.exists(new):
            QMessageBox.warning(self, "Rename", "A recording with this name already exists.")
            return
        self._release()
        try:
            os.rename(self.folder, new)
        except OSError as e:
            QMessageBox.warning(self, "Rename", f"Could not rename:\n{e}")
            return
        self.refresh()
        self._select_path(new)

    def delete_session(self):
        if not self.folder or self._busy():
            return
        size = human_size(sum(f.stat().st_size for f in os.scandir(self.folder) if f.is_file()))
        if QMessageBox.question(self, "Delete recording",
                                f"Move {os.path.basename(self.folder)} ({size}) to the recycle bin?") != QMessageBox.Yes:
            return
        self._release()
        if not to_trash(self.folder):
            QMessageBox.warning(self, "Delete", "Could not move it to the recycle bin (file in use?).")
            return
        row = self.list.currentRow()
        self.refresh()
        if self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))

    def delete_track(self):
        name = self.track.itemData(self.track.currentIndex())
        if name is None or self._busy():
            return
        kind, files = self.tracks[name]
        if QMessageBox.question(self, "Delete track",
                                f"Move the {len(files)} file(s) of '{name}' to the recycle bin?\n"
                                "The rest of the recording is kept.") != QMessageBox.Yes:
            return
        self._release()
        failed = [f for f in files if not to_trash(os.path.join(self.folder, f))]
        if failed:
            QMessageBox.warning(self, "Delete", f"{len(failed)} file(s) could not be moved to the recycle bin.")
        self.open_session(self.list.currentRow())

    def open_external(self):
        if self.source and self.source.kind == "video":
            file, _ = self.source.locate(self.pos)
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(self.folder, file)))

    def render(self):
        if not self.source or self.source.kind != "images":
            return
        fps = self.render_fps.value()
        name = self.track.itemData(self.track.currentIndex()).replace(" (images)", "")
        path = os.path.join(self.folder, f"render_{safe_name(name)}_{fps}fps.mp4")
        if os.path.exists(path) and QMessageBox.question(
                self, "Render", f"{os.path.basename(path)} already exists. Replace it?") != QMessageBox.Yes:
            return
        self.main.start_render(list(self.source.paths), path, fps)

    def closeEvent(self, event):
        self.pause()
        if self.source:
            self.source.close()
        super().closeEvent(event)
