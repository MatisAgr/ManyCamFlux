import json
import math
import os
from collections import Counter
from datetime import datetime

from PyQt5.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (QAction, QCheckBox, QComboBox, QDockWidget, QFileDialog, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar,
                             QScrollArea, QSizePolicy, QToolBar, QToolButton, QWidget)

from camera import Camera, clamp, fits, list_cameras
from dialogs import CameraPanel, CaptureSettingsDialog, fill_resolutions
from imaging import best_grid, compose_grid, draw_label, fit_size, resize, safe_name
from recorder import RenderJob, Timelapse, VideoRecorder, save_async
from utils import REPO_URL, VERSION, hms, icon, print_error, print_info, print_success, print_warning

CONFIG_PATH = os.path.join(os.path.expanduser("~"), "Documents", "ManyCamFlux", "ManyCamFlux_config.json")
MODELS_DIR = os.path.join(os.path.dirname(CONFIG_PATH), "models")  # vision models imported in the settings
DEFAULT_OUTPUT = os.path.join(os.path.expanduser("~"), "Pictures", "ManyCamFlux")
DEFAULTS = {
    "resolution": [1280, 720],
    "keep_aspect_ratio": True,
    "adaptive_resolution": True,
    "show_labels_in_screenshots": True,
    "output_folder": DEFAULT_OUTPUT,
    "timelapse_interval": 5.0,
    "timelapse_per_camera": False,
    "video_fps": 30,
    "video_per_camera": True,
    "video_motion_only": False,
    "video_motion_threshold": 1.0,
    "video_timestamp": False,
    "video_split": True,
    "show_info_bar": True,
    "timelapse_duration": 0,  # seconds, 0 = until stopped
    "video_duration": 0,
    "video_segment_minutes": 10,
    "models": [],  # vision model library: [{"name", "file", "classes", "threshold"}], replaced, never mutated
}
ACCENT = QColor(53, 132, 228)
BOX_COLORS = [QColor(80, 220, 100), QColor(255, 160, 40), QColor(60, 200, 230), QColor(240, 220, 60),
              QColor(230, 90, 200)]  # one per class index


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def load_config(path):
    """(global settings, camera settings list). Unknown keys are ignored, missing ones defaulted."""
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cfg.update({k: v for k, v in data.get("global_settings", {}).items() if k in DEFAULTS})
        return cfg, [c for c in data.get("cameras", []) if isinstance(c, dict)]
    except FileNotFoundError:
        return cfg, []


class SnapshotToast(QFrame):
    """'Snapshot saved' notice with a thumbnail, bottom-right of the window, for a few seconds.
    A click opens the image."""

    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("toast")
        self.setStyleSheet("#toast { background: rgba(24, 26, 30, 235); border: 1px solid #3a3f47;"
                           " border-radius: 8px; } QLabel { color: #e1e3e7; background: transparent; }")
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 12, 8)
        self.thumb, self.text = QLabel(), QLabel()
        layout.addWidget(self.thumb)
        layout.addWidget(self.text)
        self.timer = QTimer(self, singleShot=True, timeout=self.hide)
        self.path = None
        self.hide()

    def show_snapshot(self, img, path):
        """img: BGR image (or a reduced version of it), shown at most 200x120."""
        h, w = img.shape[:2]
        w, h = fit_size(w, h, 200, 120)
        img = resize(img, w, h)
        self.thumb.setPixmap(QPixmap.fromImage(QImage(img.data, w, h, img.strides[0], QImage.Format_BGR888).copy()))
        self.text.setText(f"<b>Snapshot saved</b><br><span style='color:#9aa0a8'>{os.path.basename(path)}</span>"
                          f"<br><span style='color:#9aa0a8'>Click to open</span>")
        self.path = path
        self.adjustSize()
        win = self.parentWidget()
        self.move(win.width() - self.width() - 16, win.height() - win.statusBar().height() - self.height() - 16)
        self.show()
        self.raise_()
        self.timer.start(4000)

    def mousePressEvent(self, event):
        self.hide()
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))


class CamFeedWidget(QWidget):
    """Paints the camera preview produced by its Camera thread, plus an info overlay."""

    def __init__(self, camera, main, parent):
        super().__init__(parent)
        self.camera, self.main = camera, main
        self._shown = None
        self.opened = (0, None)  # camera.opened as seen by the last sync_cameras
        self.setMinimumSize(160, 120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def refresh(self):
        """Repaint only when something visible changed (new frame, status, name...)."""
        c = self.camera
        key = (c.frame_id, c.status, c.label, self.main.recording(c), self.main.selected is c,
               c.model, id(c.detections), c.det_status)  # id: comparing numpy arrays raises
        if key != self._shown:
            self._shown, self._shown_dets = key, c.detections  # keep it alive so its id is not reused
            self.update()

    def resizeEvent(self, event):
        dpr = self.devicePixelRatioF()
        self.camera.display_size = (max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))

    def paintEvent(self, event):
        c, w, h = self.camera, self.width(), self.height()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(16, 17, 19))
        preview = c.preview  # read once: the thread may swap it meanwhile
        if preview is not None:
            img = preview[0]
            if self.main.keep_aspect_ratio:
                iw, ih = fit_size(img.width(), img.height(), w, h)
                target = QRectF((w - iw) / 2, (h - ih) / 2, iw, ih)
            else:
                target = QRectF(self.rect())
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(target, img)
            if c.model:
                self._draw_boxes(p, target)

        bar = 26 if self.main.cfg["show_info_bar"] else 0
        if c.model:  # vision strip, kept even without the info bar: it is the feature's only feedback
            p.fillRect(0, h - bar - 22, w, 22, QColor(0, 0, 0, 150))
            p.setPen(QColor(200, 210, 225))
            p.drawText(QRect(10, h - bar - 22, w - 20, 22), Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(self._vision_text(), Qt.ElideRight, w - 20))
        if bar:
            p.fillRect(0, h - bar, w, bar, QColor(0, 0, 0, 170))
            frame = c.frame
            info = ""
            if frame is not None:
                size, tag = f"{frame.shape[1]}×{frame.shape[0]}", c.resolution_tag(frame)
                if tag == "downscaled":
                    full = f"{size} · downscaled from {c.native[0]}×{c.native[1]} · {c.fps:.0f} fps"
                    info = full if p.fontMetrics().horizontalAdvance(full) < w * 0.65 else \
                        f"{size} · downscaled · {c.fps:.0f} fps"
                else:
                    info = f"{size}{' · native' if tag else ''} · {c.fps:.0f} fps"
            info_w = p.fontMetrics().horizontalAdvance(info) + 10
            p.setPen(QColor(170, 170, 175))
            p.drawText(QRect(0, h - bar, w - 10, bar), Qt.AlignVCenter | Qt.AlignRight, info)
            font = p.font()
            font.setBold(True)
            p.setFont(font)
            p.setPen(Qt.white)
            name = p.fontMetrics().elidedText(c.label, Qt.ElideRight, max(0, w - info_w - 20))
            p.drawText(QRect(10, h - bar, w, bar), Qt.AlignVCenter | Qt.AlignLeft, name)

        if c.status:
            p.drawText(QRect(0, 0, w, h - bar), Qt.AlignCenter, c.status)
        if self.main.recording(c):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(220, 50, 47))
            p.drawEllipse(w - 22, 10, 12, 12)
        if self.main.selected is c:
            p.setPen(QPen(ACCENT, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(self.rect()).adjusted(1, 1, -1, -1))

    def _draw_boxes(self, p, target):
        """Detections are in camera.frame pixels (already rotated/mirrored like the preview)."""
        c, frame, dets = self.camera, self.camera.frame, self.camera.detections
        if frame is None or dets is None:
            return
        sx, sy = target.width() / frame.shape[1], target.height() / frame.shape[0]
        classes = next((m["classes"] for m in self.main.cfg["models"] if m["name"] == c.model), [])
        p.setBrush(Qt.NoBrush)
        for (x1, y1, x2, y2), score, name in zip(*dets):
            color = BOX_COLORS[(classes.index(name) if name in classes else 0) % len(BOX_COLORS)]
            box = QRectF(target.x() + x1 * sx, target.y() + y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy)
            p.setPen(QPen(color, 2))
            p.drawRect(box)
            above = box.y() - 4 >= target.y() + p.fontMetrics().ascent()  # else inside, at the top of the box
            p.drawText(QPointF(box.x() + 2, box.y() - 4 if above else box.y() + p.fontMetrics().ascent() + 2),
                       f"{name} {score:.2f}")

    def _vision_text(self):
        c = self.camera
        if c.det_status:
            return f"{c.model} · {c.det_status}"
        if c.detections is None:
            return f"{c.model} · waiting for a frame…"
        found, best = Counter(c.detections[2]), {}  # insertion order: first seen first
        for name, score in zip(c.detections[2], c.detections[1]):
            best[name] = max(best.get(name, 0.0), float(score))
        labels = ", ".join(f"{n} ×{k} ({best[n]:.2f})" for n, k in found.items()) or "nothing found"
        return f"{c.model} · {c.det_fps:.1f} det/s · {labels}"

    def mousePressEvent(self, event):
        self.main.select_camera(self.camera)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.main.toggle_focus(self)

    def show_context_menu(self, pos):
        m = self.main
        menu = QMenu(self)
        menu.addAction(icon("camera"), "Snapshot this camera", lambda: m.snapshot_camera(self.camera))
        menu.addAction(icon("timer"), "Stop timelapse" if m.timelapse else "Timelapse this camera only",
                       lambda: m.toggle_timelapse(self.camera))
        menu.addAction(icon("record"), "Stop recording" if m.video else "Record this camera only",
                       lambda: m.toggle_video(self.camera))
        menu.addSeparator()
        menu.addAction(icon("rotate-left"), "Rotate left", lambda: m.rotate(self.camera, -90))
        menu.addAction(icon("rotate-right"), "Rotate right", lambda: m.rotate(self.camera, 90))
        for attr, name, text in (("flip_h", "flip-h", "Mirror horizontally"), ("flip_v", "flip-v", "Mirror vertically")):
            action = menu.addAction(icon(name), text)
            action.setCheckable(True)
            action.setChecked(getattr(self.camera, attr))
            action.toggled.connect(lambda on, a=attr: m.set_flip(self.camera, a, on))
        menu.addSeparator()
        menu.addAction(icon("focus"), "Back to grid" if m.focused is self else "Focus (double-click)",
                       lambda: m.toggle_focus(self))
        menu.addAction(icon("eye-off"), "Hide", lambda: m.set_visible(self.camera, False))
        menu.exec_(self.mapToGlobal(pos))


class CamFluxWidget(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ManyCamFlux")
        self.resize(1280, 800)
        self.feeds = {}  # device id -> CamFeedWidget, in display order
        self.focused = None
        self.selected = None
        self.timelapse = None
        self.video = None
        self.renders = []
        self.recordings = None
        self.models = {}  # vision model name -> vision.ModelWorker, while at least one camera uses it
        try:
            self.cfg, cams = load_config(CONFIG_PATH)
        except Exception as e:
            print_error(f"Ignoring unreadable config {CONFIG_PATH}: {e}")
            self.cfg, cams = dict(DEFAULTS), []
        self._store_camera_settings(cams)
        self._present = None  # camera list seen by the last sync_cameras

        self._build_ui()
        self.sync_cameras()
        self.repaint_timer = QTimer(self, timeout=self.tick)
        self.repaint_timer.start(33)
        self.hotplug_timer = QTimer(self, timeout=self.sync_cameras)  # hot-swap: watch for (un)plugged cameras
        self.hotplug_timer.start(2000)
        self.statusBar().showMessage("Double-click a camera to focus it · right-click for options", 8000)

    # ---------- UI ----------
    def _build_ui(self):
        self.flux = QWidget()
        self.grid = QGridLayout(self.flux)
        self.grid.setSpacing(6)
        self.grid.setContentsMargins(6, 6, 6, 6)
        self.empty = QLabel("No camera detected.\nPlug one in, it will show up automatically.", self.flux)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setEnabled(False)
        self.setCentralWidget(self.flux)
        self.flux.installEventFilter(self)
        self.layout_timer = QTimer(self, singleShot=True, timeout=self.update_grid_layout)

        self.panel = CameraPanel(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.panel)
        self.dock = QDockWidget("Cameras", self)
        self.dock.setObjectName("cameras")
        self.dock.setMinimumWidth(self.panel.minimumSizeHint().width() + 20)
        self.dock.setWidget(scroll)
        self.dock.setTitleBarWidget(self._dock_title_bar())
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)

        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.toolbar = tb

        self.res_combo = QComboBox()
        self.res_combo.setToolTip("Resolution of ALL cameras, up to the best native one "
                                  "(each camera is limited to its own native resolution)")
        self._natives = None
        self._select_resolution(self.cfg["resolution"])
        self.res_combo.currentIndexChanged.connect(lambda i: self.set_resolution(self.res_combo.choices[i][0]))
        tb.addWidget(self.res_combo)
        self.ratio_cb = QCheckBox("Keep ratio")
        self.ratio_cb.setChecked(self.cfg["keep_aspect_ratio"])
        self.ratio_cb.toggled.connect(self.set_keep_aspect)
        tb.addWidget(self.ratio_cb)
        tb.addSeparator()
        self._action(tb, "camera", "Snapshot", self.snapshot_all, "S", "Save one grid image of all visible cameras")
        self.tl_action = self._action(tb, "timer", "Timelapse", self.toggle_timelapse, "T",
                                      "Save images at a regular interval", checkable=True)
        self.rec_action = self._action(tb, "record", "Record", self.toggle_video, "R", "Record video", checkable=True)
        tb.addSeparator()
        self._action(tb, "library", "Recordings", self.show_recordings, "Ctrl+L", "Browse and play recordings")
        self._action(tb, "folder", "Open folder", self.open_output_folder, "Ctrl+O", "Open the output folder")
        self._action(tb, "settings", "Settings", self.show_capture_settings, "Ctrl+,", "Capture settings")
        tb.addSeparator()
        self._action(tb, "refresh", "Refresh", self.refresh_cameras, "F5",
                     "Reconnect all cameras (if a feed is frozen, black or duplicated)")
        panel = self.dock.toggleViewAction()
        panel.setText("Cameras")
        panel.setIcon(icon("sidebar"))
        panel.setShortcut("Ctrl+B")
        panel.setToolTip("Show/hide the Cameras panel (Ctrl+B)")
        tb.addAction(panel)
        self._action(tb, "fullscreen", "Fullscreen", self.toggle_fullscreen, "F11", "Toggle fullscreen")
        self._action(tb, "help", "Help", self.show_about, "F1", "Version, shortcuts and help")

        self.rec_label = QLabel()
        self.count_label = QLabel()
        self.render_bar = QProgressBar()
        self.render_bar.setRange(0, 1000)
        self.render_bar.setFixedWidth(260)
        self.render_cancel = QToolButton()
        self.render_cancel.setIcon(icon("close"))
        self.render_cancel.setAutoRaise(True)
        self.render_cancel.setToolTip("Cancel rendering")
        self.render_cancel.clicked.connect(lambda: [job.cancel() for job in self.renders])
        for w in (self.rec_label, self.render_bar, self.render_cancel, self.count_label):
            self.statusBar().addPermanentWidget(w)
        self.render_bar.hide()
        self.render_cancel.hide()
        self.toast = SnapshotToast(self)

    def _dock_title_bar(self):
        """Own title bar: Qt's float/close buttons are tiny, especially on high-DPI screens.
        Everything but the buttons lets mouse events through, so the whole bar is a drag handle."""
        bar = QWidget()
        bar.setObjectName("dockTitle")
        bar.setAttribute(Qt.WA_StyledBackground)  # let the theme paint it (hover highlight)
        bar.setMinimumHeight(40)
        bar.setCursor(Qt.OpenHandCursor)
        bar.setToolTip("Drag to move or detach the panel · double-click to detach / dock")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 4, 4)
        grip = QLabel()
        grip.setPixmap(icon("grip").pixmap(QSize(16, 16)))
        title = QLabel("Cameras")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        for w in (grip, title):  # a QLabel would swallow the press and the dock would never start dragging
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(grip)
        layout.addWidget(title, 1)
        buttons = (("float", "Detach / dock the panel", lambda: self.dock.setFloating(not self.dock.isFloating())),
                   ("close", "Close the panel (Ctrl+B)", self.dock.close))
        for name, tip, slot in buttons:
            b = QToolButton()
            b.setIcon(icon(name))
            b.setIconSize(QSize(18, 18))
            b.setAutoRaise(True)
            b.setToolTip(tip)
            b.setCursor(Qt.ArrowCursor)
            b.clicked.connect(slot)
            layout.addWidget(b)
        return bar

    def _best_native(self):
        """Largest native resolution among the cameras; None while one is still unknown (no limit yet)."""
        natives = [f.camera.native for f in self.feeds.values()]
        if not natives or None in natives:
            return None
        return max(natives, key=lambda r: r[0] * r[1])

    def _select_resolution(self, res):
        """Show res in the toolbar combo (limited to the best native one). Does not apply it."""
        fill_resolutions(self.res_combo, self._best_native(), res)

    def _check_natives(self):
        """Native resolutions arrive ~1 s after a camera opens: then limit the choices to them."""
        natives = tuple((dev, f.camera.native) for dev, f in self.feeds.items())
        if natives == self._natives:
            return
        self._natives = natives
        for f in self.feeds.values():
            cam = f.camera
            if not fits(cam.resolution, cam.native):
                cam.resolution = tuple(cam.native)  # the driver already delivers its native mode
        self.cfg["resolution"] = list(clamp(self.cfg["resolution"], self._best_native()))
        self._select_resolution(self.cfg["resolution"])
        if self.selected:
            self.panel.set_camera(self.selected)

    def _action(self, toolbar, icon_name, text, slot, shortcut, tip, checkable=False):
        action = QAction(icon(icon_name), text, self, checkable=checkable)
        action.setShortcut(shortcut)
        action.setToolTip(f"{tip} ({shortcut})")
        action.triggered.connect(lambda: slot())  # don't pass `checked` to slots with optional args
        toolbar.addAction(action)
        if checkable:
            toolbar.widgetForAction(action).setObjectName("rec")  # red when active (see theme)
        return action

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # narrow window: icons only, so every toolbar button stays reachable
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if self.width() >= 1150 else Qt.ToolButtonIconOnly)

    def eventFilter(self, obj, event):
        if obj is self.flux and event.type() == QEvent.Resize:
            self.layout_timer.start(60)
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.focused:
                self.toggle_focus(self.focused)
            elif self.isFullScreen():
                self.showNormal()
        else:
            super().keyPressEvent(event)

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def tick(self):
        self._check_natives()
        for feed in self.feeds.values():
            if feed.isVisible():
                feed.refresh()
        if self.video is not None and not self.video.is_alive():
            error = self.video.error
            self.toggle_video()
            QMessageBox.warning(self, "Recording", f"Video recording stopped:\n{error}")
        for rec, stop in ((self.video, self.toggle_video), (self.timelapse, self.toggle_timelapse)):
            if rec is not None and rec.limit and rec.elapsed() >= rec.limit:
                stop()
                self.statusBar().showMessage(f"Stopped automatically after {hms(rec.limit)}: {rec.folder}", 10000)
        text = ""
        if self.video is not None:
            v = self.video
            limit = f" / {hms(v.limit)}" if v.limit else ""
            text += (f"<span style='color:#ff5a5f'>●</span> REC {hms(v.elapsed())}{limit}"
                     f" · {v.count} frames")
            if v.motion is not None and v.written + v.skipped:
                text += f" · {100 * v.skipped // (v.written + v.skipped)}% static cut"
            text += "&nbsp;&nbsp;&nbsp;"
        if self.timelapse is not None:
            t = self.timelapse
            text += f"Timelapse #{t.count} · next in {t.remaining():.0f}s"
            if t.limit:
                text += f" · ends in {hms(max(0, t.limit - t.elapsed()))}"
        if text != self.rec_label.text():
            self.rec_label.setText(text)
        if self.renders:
            self._update_renders()

    def start_render(self, images, path, fps):
        job = RenderJob(images, path, fps)
        self.renders.append(job)
        job.start()
        self._update_renders()

    def _update_renders(self):
        for job in [j for j in self.renders if not j.is_alive()]:
            self.renders.remove(job)
            if job.error:
                QMessageBox.warning(self, "Render", f"Rendering failed:\n{job.error}")
            elif job.cancelled:
                self.statusBar().showMessage("Rendering cancelled", 5000)
            else:
                self.notify(f"Rendered: {job.path}")
                if self.recordings is not None and self.recordings.isVisible():
                    self.recordings.refresh()
        busy = bool(self.renders)
        self.render_bar.setVisible(busy)
        self.render_cancel.setVisible(busy)
        if busy:
            n = len(self.renders)
            self.render_bar.setFormat(f"Rendering {n} video{'s' if n > 1 else ''}… %p%")
            self.render_bar.setValue(int(1000 * sum(j.progress for j in self.renders) / n))

    def show_recordings(self):
        if self.recordings is None:
            from recordings import RecordingsDialog  # loaded on first use: keeps startup fast
            self.recordings = RecordingsDialog(self)
        self.recordings.refresh()
        self.recordings.show()
        self.recordings.raise_()
        self.recordings.activateWindow()

    def notify(self, message):
        print_success(message)
        self.statusBar().showMessage(message, 6000)

    # ---------- cameras ----------
    @property
    def keep_aspect_ratio(self):
        return self.cfg["keep_aspect_ratio"]

    def recording(self, cam):
        """True if a timelapse or video is capturing cam."""
        return any(r is not None and r.device in (None, cam.device) for r in (self.timelapse, self.video))

    def _store_camera_settings(self, cams):
        """Settings are matched to cameras by device id; old configs (no id) by order."""
        self.saved_cams = {c["device"]: c for c in cams if "device" in c}
        self.legacy_cams = [c for c in cams if "device" not in c]

    def sync_cameras(self):
        present = list_cameras()
        ids = {cam[0] for cam in present}
        gone = [dev for dev in self.feeds if dev not in ids]
        for dev in gone:
            self.remove_camera(dev)
        changed, self._present = present != self._present, present
        added = False
        for dev, desc, index, qt_name in present:
            if dev in self.feeds:
                feed, cam = self.feeds[dev], self.feeds[dev].camera
                cam.index = index  # indices shift when another camera is unplugged
                # a (re)open racing a (un)plug may have used a stale index, i.e. grabbed another camera: redo it
                opened = cam.opened
                if opened != feed.opened and (changed or opened[1] != index):
                    cam.reopen(cam.resolution)
                feed.opened = opened
            else:
                self.add_camera(dev, desc, index, qt_name)
                added = True
        if gone or added:
            self.update_grid_layout()
            self.panel.refresh()
            n = len(self.feeds)
            self.count_label.setText(f"{n} camera{'s' if n != 1 else ''}")

    def refresh_cameras(self):
        """Close and reopen every camera; settings are kept (restored like a re-plug)."""
        for dev in list(self.feeds):
            self.remove_camera(dev)
        self._present = None
        self.sync_cameras()

    def add_camera(self, device, description, index, qt_name=None):
        cam = Camera(device, description, index, tuple(self.cfg["resolution"]))
        if any(f.camera.label == cam.label for f in self.feeds.values()):
            cam.label = f"{description} ({len(self.feeds) + 1})"
        # qt_name: the id used before 2.2 (Qt device name), so settings saved under it carry over to the port once
        saved = (self.saved_cams.pop(device, None) or self.saved_cams.pop(qt_name, None)
                 or (self.legacy_cams.pop(0) if self.legacy_cams else None))
        if saved:
            cam.apply_settings(saved)
        cam.keep_aspect = self.keep_aspect_ratio
        self.feeds[device] = CamFeedWidget(cam, self, self.flux)
        cam.start()
        if cam.model:
            self.set_camera_model(cam, cam.model)
        self.notify(f"Camera connected: {cam.label}")

    def remove_camera(self, device):
        feed = self.feeds.pop(device)
        cam = feed.camera
        cam.stop()
        self.saved_cams[device] = cam.settings()  # restored if it is plugged back in
        self.set_camera_model(cam, None)
        if self.focused is feed:
            self.focused = None
        if self.selected is cam:
            self.selected = None
        feed.deleteLater()
        print_warning(f"Camera disconnected: {cam.label}")
        self.statusBar().showMessage(f"Camera disconnected: {cam.label}", 6000)

    def set_camera_model(self, cam, name):
        """Run the library model `name` on cam (None: no model). A model is loaded once for all the
        cameras using it, and unloaded when the last one leaves."""
        for key, worker in list(self.models.items()):
            if cam in worker.cameras:
                worker.cameras = tuple(c for c in worker.cameras if c is not cam)
                if not worker.cameras:
                    worker.stop()
                    del self.models[key]
        entry = next((m for m in self.cfg["models"] if m["name"] == name), None)
        cam.model, cam.detections, cam.det_fps = name, None, 0.0
        cam.det_status = "Model not found" if name and entry is None else ""
        if entry is None:
            return
        worker = self.models.get(name)
        if worker is None:
            from vision import ModelWorker  # loaded on first use: keeps onnxruntime out of startup
            worker = self.models[name] = ModelWorker(entry, MODELS_DIR)
            worker.cameras = (cam,)
            worker.start()
        else:
            worker.cameras += (cam,)

    def update_grid_layout(self):
        while self.grid.count():
            self.grid.takeAt(0)
        for i in range(self.grid.rowCount()):
            self.grid.setRowStretch(i, 0)
        for i in range(self.grid.columnCount()):
            self.grid.setColumnStretch(i, 0)
        feeds = [self.focused] if self.focused else [f for f in self.feeds.values() if f.camera.visible]
        for f in self.feeds.values():
            f.setVisible(f in feeds)
        self.empty.setVisible(not feeds)
        if not feeds:
            self.empty.setText("No camera detected.\nPlug one in, it will show up automatically." if not self.feeds
                               else "All cameras are hidden.\nShow them from the Cameras panel.")
            self.grid.addWidget(self.empty, 0, 0)
            self.grid.setRowStretch(0, 1)
            self.grid.setColumnStretch(0, 1)
            return
        ratios = [f.camera.frame.shape[1] / f.camera.frame.shape[0] for f in feeds if f.camera.frame is not None]
        res = self.cfg["resolution"]
        aspect = sum(ratios) / len(ratios) if ratios else res[0] / res[1]
        rows, cols = best_grid(len(feeds), self.flux.width(), self.flux.height(), aspect)
        last_row = len(feeds) - (rows - 1) * cols
        # each camera spans 2 grid columns so an incomplete last row can be centred by a half-cell offset
        for i, f in enumerate(feeds):
            r, c = divmod(i, cols)
            offset = cols - last_row if r == rows - 1 else 0
            self.grid.addWidget(f, r, 2 * c + offset, 1, 2)
        for r in range(rows):
            self.grid.setRowStretch(r, 1)
        for c in range(2 * cols):
            self.grid.setColumnStretch(c, 1)

    def select_camera(self, cam):
        self.selected = cam
        self.panel.set_camera(cam)

    def toggle_focus(self, feed):
        self.focused = None if self.focused is feed else feed
        self.update_grid_layout()

    def set_visible(self, cam, visible):
        cam.visible = visible
        if self.focused and self.focused.camera is cam:
            self.focused = None
        self.update_grid_layout()
        if self.selected is cam:
            self.panel.set_camera(cam)

    def rotate(self, cam, delta):
        cam.rotation = (cam.rotation + delta) % 360
        if self.selected is cam:
            self.panel.set_camera(cam)
        QTimer.singleShot(300, self.update_grid_layout)  # once a rotated frame exists

    def set_flip(self, cam, attr, on):
        setattr(cam, attr, on)
        if self.selected is cam:
            self.panel.set_camera(cam)

    def set_resolution(self, res):
        """Toolbar: the default resolution, applied to every camera."""
        if list(res) == list(self.cfg["resolution"]):
            return
        self.cfg["resolution"] = list(res)
        for f in self.feeds.values():
            f.camera.reopen(clamp(res, f.camera.native))  # never above what each camera can do
        if self.selected:
            self.panel.set_camera(self.selected)
        print_info(f"Resolution of all cameras set to {res[0]}x{res[1]} (at most their native one)")
        QTimer.singleShot(2000, self.update_grid_layout)

    def set_camera_resolution(self, cam, res):
        res = clamp(res, cam.native)
        if res != tuple(cam.resolution):
            cam.reopen(tuple(res))
            print_info(f"{cam.label}: resolution set to {res[0]}x{res[1]}")
            QTimer.singleShot(2000, self.update_grid_layout)

    def set_keep_aspect(self, on):
        self.cfg["keep_aspect_ratio"] = on
        for f in self.feeds.values():
            f.camera.keep_aspect = on
            f.update()

    # ---------- capture ----------
    def shots(self, device=None):
        """Latest frame of each visible camera (or of `device` only): [(device, label, frame, frame_id)]. Thread-safe."""
        cams = [f.camera for f in list(self.feeds.values())]
        return [(c.device, c.label, c.frame, c.frame_id) for c in cams
                if c.visible and c.frame is not None and device in (None, c.device)]

    def compose(self, shots, max_width=None):
        names = [s[1] for s in shots] if self.cfg["show_labels_in_screenshots"] else None
        # cell = largest camera frame (as landscape): cameras can each have their own resolution
        w = max(max(s[2].shape[:2]) for s in shots)
        h = max(min(s[2].shape[:2]) for s in shots)
        cols = math.ceil(math.sqrt(len(shots)))
        if max_width and cols * w > max_width:  # shrink cells before composing: far cheaper than resizing after
            scale = max_width / (cols * w)
            w, h = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2
        return compose_grid([s[2] for s in shots], names, (w, h), self.cfg["adaptive_resolution"])

    def compose_video(self, shots):
        # a 4K grid cannot be encoded in real time (measured 19 fps for 7 cameras); 1080p width keeps 30 fps
        return self.compose(shots, max_width=1920)

    def output_dir(self, sub):
        path = os.path.join(self.cfg["output_folder"] or DEFAULT_OUTPUT, sub)
        os.makedirs(path, exist_ok=True)
        return path

    def snapshot_all(self):
        shots = self.shots()
        if not shots:
            self.statusBar().showMessage("No camera image to capture", 4000)
            return
        path = os.path.join(self.output_dir("snapshots"), f"snapshot_all_{stamp()}.jpg")
        save_async(path, lambda: self.compose(shots))
        self.notify(f"Snapshot saved: {path}")
        self.toast.show_snapshot(self.compose(shots, max_width=480), path)  # small cells: cheap

    def snapshot_camera(self, cam):
        frame = cam.frame
        if frame is None:
            return
        label = cam.label if self.cfg["show_labels_in_screenshots"] else None
        path = os.path.join(self.output_dir("snapshots"), f"snapshot_{safe_name(cam.label)}_{stamp()}.jpg")
        save_async(path, lambda: draw_label(frame.copy(), label) if label else frame)
        self.notify(f"Snapshot saved: {path}")
        self.toast.show_snapshot(frame, path)

    def toggle_timelapse(self, cam=None):
        """Start (all visible cameras, or `cam` only) or stop the timelapse."""
        try:
            if self.timelapse:
                n, folder = self.timelapse.stop(), self.timelapse.folder
                self.timelapse = None
                self.notify(f"Timelapse stopped: {n} frames in {folder}")
            else:
                folder = self.output_dir(f"timelapse_{stamp()}")
                device = cam.device if cam else None
                self.timelapse = Timelapse(folder, self.cfg["timelapse_interval"],
                                           self.cfg["timelapse_per_camera"] or cam is not None,
                                           lambda: self.shots(device), self.compose)
                self.timelapse.limit = self.cfg["timelapse_duration"]
                self.timelapse.device = device
                self.notify(f"Timelapse{f' of {cam.label}' if cam else ''} started every "
                            f"{self.cfg['timelapse_interval']:g}s → {folder}")
        except OSError as e:
            QMessageBox.warning(self, "Timelapse", str(e))
        self.tl_action.setChecked(self.timelapse is not None)

    def toggle_video(self, cam=None):
        """Start (all visible cameras, or `cam` only) or stop the video recording."""
        try:
            if self.video:
                n, folder, dropped = self.video.stop(), self.video.folder, self.video.dropped
                self.video = None
                lost = f" ({dropped} dropped: encoder too slow, see frames.csv)" if dropped else ""
                if self.recordings is not None and self.recordings.isVisible():
                    self.recordings.refresh()
                self.notify(f"Recording stopped: {n} frames in {folder}{lost}")
            else:
                folder = self.output_dir(f"video_{stamp()}")
                c = self.cfg
                device = cam.device if cam else None
                self.video = VideoRecorder(folder, c["video_fps"], c["video_per_camera"] or cam is not None,
                                           lambda: self.shots(device), self.compose_video,
                                           motion=c["video_motion_threshold"] if c["video_motion_only"] else None,
                                           timestamp=c["video_timestamp"],
                                           segment_minutes=c["video_segment_minutes"] if c["video_split"] else None)
                self.video.limit = c["video_duration"]
                self.video.device = device
                self.video.start()
                risk = "" if self.cfg["video_split"] else " (single file: unreadable if interrupted)"
                self.notify(f"Recording{f' {cam.label}' if cam else ''} at {self.cfg['video_fps']} fps → {folder}{risk}")
        except OSError as e:
            QMessageBox.warning(self, "Recording", str(e))
        self.rec_action.setChecked(self.video is not None)

    def open_output_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir("")))

    def show_capture_settings(self):
        dialog = CaptureSettingsDialog(self.cfg, self, MODELS_DIR)
        if dialog.exec_():
            self.cfg.update(dialog.values())
            for dev in dialog.forgotten:  # unplugged cameras whose settings the user deleted
                self.saved_cams.pop(dev, None)
            renamed = dialog.renamed()  # one pass, so swapping two names works
            self.models = {renamed.get(name, name): worker for name, worker in self.models.items()}
            for f in self.feeds.values():
                f.camera.model = renamed.get(f.camera.model, f.camera.model)
            for settings in list(self.saved_cams.values()) + self.legacy_cams:  # unplugged cameras
                if settings.get("model") in renamed:
                    settings["model"] = renamed[settings["model"]]
            library = {m["name"]: m for m in self.cfg["models"]}
            for name, worker in self.models.items():
                worker.entry = library.get(name, worker.entry)  # classes and threshold apply live
            for f in self.feeds.values():
                if f.camera.model and f.camera.model not in library:
                    self.set_camera_model(f.camera, None)
            self.panel.refresh_models()
            self.save_config()
            for f in self.feeds.values():
                f.update()

    def show_about(self):
        QMessageBox.about(self, "About ManyCamFlux", f"""
            <h2>ManyCamFlux {VERSION}</h2>
            <p>View, capture and record many webcams at once.</p>
            <table cellspacing="4">
            <tr><td><b>S</b></td><td>Snapshot of all cameras</td></tr>
            <tr><td><b>T</b> / <b>R</b></td><td>Start/stop timelapse / video</td></tr>
            <tr><td><b>Ctrl+L</b></td><td>Recordings (play, rename, delete, render)</td></tr>
            <tr><td><b>F5</b></td><td>Reconnect all cameras (frozen, black or duplicated feed)</td></tr>
            <tr><td><b>Ctrl+B</b></td><td>Cameras panel (drag its title bar to detach it)</td></tr>
            <tr><td><b>Ctrl+,</b></td><td>Capture settings</td></tr>
            <tr><td><b>F11</b> / <b>Esc</b></td><td>Fullscreen / back to the grid</td></tr>
            <tr><td>Double-click</td><td>Show one camera alone</td></tr>
            </table>
            <p>Output: {self.output_dir("")}<br>Settings: {CONFIG_PATH}</p>
            <p><a href="{REPO_URL}">{REPO_URL}</a></p>
            <p>Free software under the GNU GPL v3, with no warranty.
            Source code and license: link above.</p>""")

    # ---------- config ----------
    def save_config(self, notify=False):
        cams = [f.camera.settings() for f in self.feeds.values()] + list(self.saved_cams.values()) + self.legacy_cams
        data = {"global_settings": self.cfg, "cameras": cams}
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            os.replace(tmp, CONFIG_PATH)  # atomic: a crash mid-write never corrupts the config
            if notify:
                self.notify(f"Configuration saved: {CONFIG_PATH}")
        except OSError as e:
            print_error(f"Failed to save configuration: {e}")
            QMessageBox.warning(self, "Configuration", f"Failed to save configuration:\n{e}")

    def import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import configuration", os.path.dirname(CONFIG_PATH),
                                              "JSON files (*.json)")
        if not path:
            return
        try:
            cfg, cams = load_config(path)
        except Exception as e:
            QMessageBox.warning(self, "Configuration", f"Failed to load configuration:\n{e}")
            return
        # the model library is files on this PC: a config (maybe from another PC) never replaces it
        self.cfg.update({k: v for k, v in cfg.items() if k not in ("resolution", "keep_aspect_ratio", "models")})
        self._select_resolution(cfg["resolution"])  # first: it applies to all, per-camera settings come after
        self.set_resolution(self.res_combo.choices[self.res_combo.currentIndex()][0])
        self.ratio_cb.setChecked(cfg["keep_aspect_ratio"])
        self._store_camera_settings(cams)
        for f in self.feeds.values():
            cam = f.camera
            saved = self.saved_cams.pop(cam.device, None) or (self.legacy_cams.pop(0) if self.legacy_cams else None)
            if saved:
                before = cam.resolution
                cam.apply_settings(saved)
                if cam.resolution != before:
                    cam.reopen(clamp(cam.resolution, cam.native))
                self.set_camera_model(cam, cam.model)
        self.update_grid_layout()
        self.panel.refresh()
        self.notify(f"Configuration imported: {path}")

    def closeEvent(self, event):
        self.repaint_timer.stop()
        self.hotplug_timer.stop()
        if self.video:
            self.toggle_video()
        if self.timelapse:
            self.toggle_timelapse()
        self.save_config()
        for job in self.renders:  # a half-rendered file is deleted by the job itself
            job.cancel()
            job.join(timeout=3)
        cams = [f.camera for f in self.feeds.values()]
        workers = list(self.models.values())
        for t in cams + workers:
            t.stop()
        for t in cams + workers:
            t.join(timeout=1)
        event.accept()
