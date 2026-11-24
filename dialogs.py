import copy
import os

from PyQt5.QtCore import QFile, QRectF, QRegularExpression, QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QRegularExpressionValidator
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
                             QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from camera import clamp, ping_text, resolution_choices, source_label
from utils import hms, icon, parse_hms


def fill_resolutions(combo, native, current):
    """Offer only what a camera can deliver (nothing above `native`) and select `current`
    (clamped to native). The chosen resolution is combo.choices[index][0]. No signal emitted."""
    current = clamp(current, native)
    combo.choices = resolution_choices(native, current)
    combo.blockSignals(True)
    combo.clear()
    combo.addItems([label for _, label in combo.choices])
    combo.setCurrentIndex([r for r, _ in combo.choices].index(current))
    combo.blockSignals(False)


SKETCH_COLORS = [QColor(53, 132, 228), QColor(46, 194, 126), QColor(229, 165, 10), QColor(192, 97, 203)]


def mode_sketch(per_camera):
    """Small diagram of an output mode: 4 cameras -> one grid file, or one file per camera."""
    dpr = QApplication.instance().devicePixelRatio()
    pm = QPixmap(int(260 * dpr), int(52 * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grey = QColor(150, 155, 165)

    def tile(x, y, w, h, color):
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(x, y, w, h), 2, 2)

    for i, c in enumerate(SKETCH_COLORS):  # the cameras
        tile(2 + (i % 2) * 30, 4 + (i // 2) * 24, 26, 20, c)
    p.setPen(QPen(grey, 2))
    p.drawLine(72, 26, 100, 26)
    p.drawLine(94, 20, 100, 26)
    p.drawLine(94, 32, 100, 26)
    if per_camera:
        for i, c in enumerate(SKETCH_COLORS):
            tile(112 + i * 34, 12, 28, 28, c)
    else:
        p.setPen(QPen(grey, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(112, 2, 60, 48))
        for i, c in enumerate(SKETCH_COLORS):
            tile(115 + (i % 2) * 28.5, 5 + (i // 2) * 22.5, 25.5, 19.5, c)
    p.end()
    return pm


def sketch_label(combo, ext):
    """mode_sketch for the combo's choice (index 1 = per camera) with a caption, kept in sync."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    picture, caption = QLabel(), QLabel()
    caption.setEnabled(False)  # greyed, like the other hints
    caption.setWordWrap(True)
    layout.addWidget(picture)
    layout.addWidget(caption)

    def update(i):
        picture.setPixmap(mode_sketch(bool(i)))
        caption.setText(f"4 files ({ext}): one per camera, full resolution" if i else
                        f"1 file ({ext}): all cameras in a grid")
    combo.currentIndexChanged.connect(update)
    update(combo.currentIndex())
    return box


def section(title, layout_cls=QFormLayout):
    """A titled box: one per settings category."""
    box = QGroupBox(title.upper())
    return box, layout_cls(box)


class DurationField(QWidget):
    """'Stop after' checkbox + hh:mm:ss field. value(): seconds, 0 = no limit."""

    def __init__(self, seconds):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.check = QCheckBox("Stop automatically after")
        self.edit = QLineEdit(hms(seconds or 3600))
        self.edit.setPlaceholderText("hh:mm:ss")
        self.edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,3}(:[0-5]?\d){0,2}")))
        self.edit.setToolTip("Duration as hh:mm:ss (hours can go above 24)")
        self.edit.setMaximumWidth(110)
        self.check.toggled.connect(self.edit.setEnabled)
        self.check.setChecked(bool(seconds))
        self.edit.setEnabled(bool(seconds))
        layout.addWidget(self.check)
        layout.addWidget(self.edit)
        layout.addStretch(1)

    def value(self):
        return parse_hms(self.edit.text()) if self.check.isChecked() else 0


class SliderWithValue(QWidget):
    """Slider with an editable numeric value next to it."""

    def __init__(self, min_val=-50, max_val=50, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.spin = QSpinBox()
        self.spin.setButtonSymbols(QSpinBox.NoButtons)
        self.spin.setFixedWidth(44)
        self.spin.setAlignment(Qt.AlignRight)
        for w in (self.slider, self.spin):
            w.setRange(min_val, max_val)
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)
        self.valueChanged = self.slider.valueChanged

    def setValue(self, value):
        self.slider.setValue(value)

    def value(self):
        return self.slider.value()


class CameraPanel(QWidget):
    """Side panel editing the selected camera; changes apply live."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.cam = None
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._pick)
        layout.addWidget(self.combo)

        self.editor = QWidget()
        ev = QVBoxLayout(self.editor)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(10)

        box, form = section("Camera")
        self.name = QLineEdit()
        self.name.textEdited.connect(self._rename)
        form.addRow("Name", self.name)
        self.port = QLabel()
        form.addRow("USB port", self.port)
        self.visible = QCheckBox("Show in grid")
        self.visible.toggled.connect(lambda on: self.cam and self.main.set_visible(self.cam, on))
        form.addRow("", self.visible)
        self.res = QComboBox()
        self.res.setToolTip("Resolution of this camera (it picks the closest it supports)")
        self.res.currentIndexChanged.connect(
            lambda i: self.cam and i >= 0 and self.main.set_camera_resolution(self.cam, self.res.choices[i][0]))
        form.addRow("Resolution", self.res)
        ev.addWidget(box)

        box, form = section("Image")
        self.sliders = {}
        for key in ("brightness", "contrast", "saturation"):
            s = SliderWithValue()
            s.valueChanged.connect(lambda v, k=key: self.cam and setattr(self.cam, k, v))
            form.addRow(key.capitalize(), s)
            self.sliders[key] = s
        reset = QPushButton("Reset image and mirror")
        reset.clicked.connect(self._reset)
        form.addRow("", reset)
        ev.addWidget(box)

        box, form = section("Orientation")
        rot = QHBoxLayout()
        left, right = QPushButton(icon("rotate-left"), " Left"), QPushButton(icon("rotate-right"), " Right")
        left.clicked.connect(lambda: self.cam and self.main.rotate(self.cam, -90))
        right.clicked.connect(lambda: self.cam and self.main.rotate(self.cam, 90))
        self.rot_label = QLabel("0°")
        self.rot_label.setAlignment(Qt.AlignCenter)
        rot.addWidget(left)
        rot.addWidget(self.rot_label, 1)
        rot.addWidget(right)
        form.addRow("Rotation", rot)
        mirror = QHBoxLayout()
        self.flips = {}
        for attr, name, text in (("flip_h", "flip-h", " Horizontal"), ("flip_v", "flip-v", " Vertical")):
            b = QPushButton(icon(name), text)
            b.setCheckable(True)
            b.toggled.connect(lambda on, a=attr: self.cam and self.main.set_flip(self.cam, a, on))
            mirror.addWidget(b)
            self.flips[attr] = b
        form.addRow("Mirror", mirror)
        ev.addWidget(box)

        box, form = section("Vision")
        self.model_combo = QComboBox()
        self.model_combo.setToolTip("Object detection model run on this camera (display only). "
                                    "Import models in the settings (Ctrl+,)")
        self.model_combo.currentIndexChanged.connect(
            lambda i: self.cam and i >= 0 and self.main.set_camera_model(self.cam, self.model_combo.itemData(i)))
        form.addRow("Model", self.model_combo)
        ev.addWidget(box)
        layout.addWidget(self.editor)
        layout.addStretch(1)

        box, cfg = section("Configuration", QVBoxLayout)
        hint = QLabel("Settings are saved automatically on exit.")
        hint.setWordWrap(True)
        hint.setEnabled(False)
        cfg.addWidget(hint)
        buttons = QHBoxLayout()
        save, load = QPushButton("Save"), QPushButton("Import…")
        save.clicked.connect(lambda: self.main.save_config(notify=True))
        load.clicked.connect(self.main.import_config)
        buttons.addWidget(save)
        buttons.addWidget(load)
        cfg.addLayout(buttons)
        layout.addWidget(box)
        self.set_camera(None)

    def refresh_models(self):
        """Fill the model choice from the library and select the current camera's model. No signal emitted."""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem("None", None)
        for m in self.main.cfg["models"]:
            self.model_combo.addItem(m["name"], m["name"])
        if self.cam and self.cam.model and self.model_combo.findData(self.cam.model) < 0:
            self.model_combo.addItem(f"{self.cam.model} (missing)", self.cam.model)  # so "None" can clear it
        self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(self.cam.model)) if self.cam else 0)
        self.model_combo.blockSignals(False)

    def refresh(self):
        """Rebuild the camera list (after hot-plug or import)."""
        cams = [f.camera for f in self.main.feeds.values()]
        self.combo.blockSignals(True)
        self.combo.clear()
        for c in cams:
            self.combo.addItem(c.label, c.device)
        self.combo.blockSignals(False)
        self.main.select_camera(self.cam if self.cam in cams else (cams[0] if cams else None))

    def set_camera(self, cam):
        self.cam = cam
        self.editor.setEnabled(cam is not None)
        self.refresh_models()
        if cam is None:
            self.name.clear()
            self.rot_label.setText("")
            return
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(self.combo.findData(cam.device))
        self.combo.blockSignals(False)
        self.name.setText(cam.label)
        self.port.setText(source_label(cam.device) or "unknown")
        device = cam.device.removeprefix("host:")
        network = device != cam.device or "://" in device  # served by a stream mirror, or a stream URL
        self.port.setToolTip(("Network stream (Settings > Cameras)\n" if network else "")
                             + ("The settings belong to this port: any camera plugged into it gets them.\n"
                                + device.removeprefix("usb:") if device.startswith("usb:") else
                                device if "://" in device else
                                "Identified by its device name (not a USB camera, or port not found)"))
        fill_resolutions(self.res, cam.native, cam.resolution)
        mirrored = device != cam.device  # a mirror scales its stream to the chosen size
        self.res.setEnabled(not network or mirrored)  # a plain stream URL: its sender sets the size
        self.res.setToolTip("Set by the stream's sender" if network and not mirrored else "")
        for w, checked in [(self.visible, cam.visible)] + [(b, getattr(cam, a)) for a, b in self.flips.items()]:
            w.blockSignals(True)
            w.setChecked(checked)
            w.blockSignals(False)
        for key, s in self.sliders.items():
            s.setValue(getattr(cam, key))
        self.rot_label.setText(f"{cam.rotation}°")

    def _pick(self, i):
        feed = self.main.feeds.get(self.combo.itemData(i))
        if feed:
            self.main.select_camera(feed.camera)

    def _rename(self, text):
        self.cam.label = text
        self.combo.setItemText(self.combo.currentIndex(), text)

    def _reset(self):
        for s in self.sliders.values():
            s.setValue(0)
        for b in self.flips.values():
            b.setChecked(False)


class CaptureSettingsDialog(QDialog):
    def __init__(self, cfg, parent=None, models_dir=""):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        pages = []

        def page(title):
            """A tab whose content scrolls if the screen is too small."""
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            inner = QWidget()
            scroll.setWidget(inner)
            tabs.addTab(scroll, title)
            pages.append(inner)
            return inner

        columns = QHBoxLayout(page("Capture"))
        columns.setSpacing(12)
        left, right = QVBoxLayout(), QVBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        box, form = section("Output")
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(cfg["output_folder"])
        browse = QPushButton(icon("folder"), " Browse…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        form.addRow("Folder", folder_row)
        right.addWidget(box)

        cams_page = QVBoxLayout(page("Cameras"))
        box, form = section("Cameras", QVBoxLayout)
        self.cam_table = QTableWidget(0, 4)
        self.cam_table.setHorizontalHeaderLabels(["Live", "Name", "Source", "Status"])
        self.cam_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cam_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.cam_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cam_table.itemSelectionChanged.connect(self._selection_changed)
        self.cam_table.verticalHeader().hide()
        self.cam_table.setIconSize(QSize(96, 54))
        self.cam_table.verticalHeader().setDefaultSectionSize(60)
        self.cam_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.cam_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        form.addWidget(self.cam_table, 1)
        hint = QLabel("Settings belong to the USB port: any camera plugged into a port gets its name and settings. "
                      "Rename cameras in the Cameras panel.")
        hint.setWordWrap(True)
        hint.setEnabled(False)
        form.addWidget(hint)
        forget_row = QHBoxLayout()
        self.forget = QPushButton(icon("trash"), " Forget selected")
        self.forget.setToolTip("Delete the saved name and settings of the selected unplugged cameras")
        self.forget.clicked.connect(self._forget_selected)
        forget_row.addWidget(self.forget)
        forget_row.addStretch(1)
        form.addLayout(forget_row)
        cams_page.addWidget(box)

        box, form = section("Network cameras", QVBoxLayout)
        self.stream_urls = QPlainTextEdit("\n".join(cfg["stream_urls"]))
        self.stream_urls.setPlaceholderText("http://127.0.0.1:8090/cams\nhttp://192.168.1.20:8080/video\n"
                                            "rtsp://192.168.1.21:554/stream1")
        self.stream_urls.setFixedHeight(90)
        form.addWidget(self.stream_urls)
        hint = QLabel("One URL per line, shown next to the USB cameras. Any stream FFmpeg reads works: MJPEG over "
                      "HTTP (IP cameras, phone apps, ESP32-CAM), RTSP, HLS (.m3u8). Not a still image (.jpg).<br>"
                      "<b>Stream mirror</b>: a URL ending in <code>/cams</code> (e.g. a VisionHost's "
                      "<code>http://127.0.0.1:8090/cams</code>) adds all the cameras it serves. Useful when another "
                      "program needs the same USB cameras: a USB camera opens in one program only, so the mirror "
                      "opens them and both read its streams. The USB cameras it serves are not opened here.")
        hint.setWordWrap(True)
        hint.setEnabled(False)
        form.addWidget(hint)
        cams_page.addWidget(box)
        self.forgotten = set()  # device ids of unplugged cameras to forget, applied on OK
        self._shown_rows = None
        self._fill_cameras()
        self._selection_changed()
        QTimer(self, timeout=self._fill_cameras).start(500)  # live: plug a camera and watch it appear

        box, form = section("Timelapse")
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.2, 3600)
        self.interval.setDecimals(1)
        self.interval.setSuffix(" s")
        self.interval.setValue(cfg["timelapse_interval"])
        form.addRow("Interval", self.interval)
        self.tl_mode = QComboBox()
        self.tl_mode.addItems(["One grid image", "One image per camera"])
        self.tl_mode.setCurrentIndex(int(cfg["timelapse_per_camera"]))
        form.addRow("Output", self.tl_mode)
        form.addRow("", sketch_label(self.tl_mode, ".jpg per shot"))
        self.tl_duration = DurationField(cfg["timelapse_duration"])
        form.addRow("Duration", self.tl_duration)
        left.addWidget(box)

        box, form = section("Video")
        self.fps = QSpinBox()
        self.fps.setRange(1, 120)
        self.fps.setSuffix(" fps")
        self.fps.setValue(cfg["video_fps"])
        form.addRow("Frame rate", self.fps)
        self.video_mode = QComboBox()
        self.video_mode.addItems(["One grid video", "One video per camera"])
        self.video_mode.setCurrentIndex(int(cfg["video_per_camera"]))
        form.addRow("Output", self.video_mode)
        form.addRow("", sketch_label(self.video_mode, ".mp4"))
        self.video_duration = DurationField(cfg["video_duration"])
        form.addRow("Duration", self.video_duration)
        self.timestamp = QCheckBox("Burn date and time into the video")
        self.timestamp.setToolTip("Like a surveillance camera: with \"Cut static scenes\", the jumps of the "
                                  "clock show when nothing happened")
        self.timestamp.setChecked(cfg["video_timestamp"])
        form.addRow("", self.timestamp)
        left.addWidget(box)

        box, form = section("Long recordings")
        self.motion = QCheckBox("Cut static scenes (motion detection)")
        self.motion.setToolTip("Only write frames where something moves (plus 2 s after): ideal for very long recordings")
        self.motion.setChecked(cfg["video_motion_only"])
        form.addRow("", self.motion)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.05, 20)
        self.threshold.setDecimals(1)
        self.threshold.setSingleStep(0.5)
        self.threshold.setSuffix(" % of the image")
        self.threshold.setToolTip("How big a change must be to count as motion (lower = more sensitive)")
        self.threshold.setValue(cfg["video_motion_threshold"])
        form.addRow("Min. moving area", self.threshold)
        tip = QLabel("💡 <b>Which value?</b> In 1080p, a hand ≈ 0.6 %, a person far away ≈ 1.2 %, "
                     "a person nearby ≈ 9 %.<br><b>1 %</b> suits most scenes, <b>2-3 %</b> outdoors "
                     "(leaves, rain). Small light changes are ignored whatever the value.")
        tip.setWordWrap(True)
        tip.setStyleSheet("QLabel { background: #1f2a3a; border: 1px solid #2d3f57; border-radius: 6px;"
                          " padding: 6px 8px; color: #c8d4e6; } QLabel:disabled { color: #6b7280; }")
        form.addRow("", tip)
        for w in (self.threshold, tip):
            w.setEnabled(self.motion.isChecked())
            self.motion.toggled.connect(w.setEnabled)
        split_row = QHBoxLayout()
        self.split = QCheckBox("Split files every")
        self.split.setChecked(cfg["video_split"])
        self.segment = QSpinBox()
        self.segment.setRange(1, 240)
        self.segment.setSuffix(" min")
        self.segment.setValue(cfg["video_segment_minutes"])
        split_row.addWidget(self.split)
        split_row.addWidget(self.segment)
        split_row.addStretch(1)
        form.addRow("", split_row)
        self.split_warning = QLabel("<b>Risk:</b> one single file: a crash, power cut or full disk makes the whole video "
                                    "unreadable. Keep it for short recordings.")
        self.split_warning.setWordWrap(True)
        self.split_warning.setStyleSheet("color: #f0a030;")
        form.addRow("", self.split_warning)
        self.split.toggled.connect(self._split_toggled)
        self._split_toggled(self.split.isChecked(), warn=False)
        right.addWidget(box)

        box, form = section("Display")
        self.info_bar = QCheckBox("Show the info bar under each camera (name, resolution, fps)")
        self.info_bar.setChecked(cfg["show_info_bar"])
        form.addRow("", self.info_bar)
        right.addWidget(box)

        vision_page = QVBoxLayout(page("Vision models"))
        box, form = section("Vision models")
        self.models_dir, self.models = models_dir, copy.deepcopy(cfg["models"])
        self._original = [(m, m["name"]) for m in self.models]  # for renamed()
        self.imported, self.removed = [], []  # files: trashed on cancel / on OK
        self.model_list = QListWidget()
        self.model_list.setMaximumHeight(160)
        self.model_list.addItems([m["name"] for m in self.models])
        form.addRow(self.model_list)
        buttons = QHBoxLayout()
        add, remove = QPushButton("Import…"), QPushButton("Remove")
        add.setToolTip("RF-DETR model exported to ONNX")
        add.clicked.connect(self._browse_model)
        remove.clicked.connect(self.remove_model)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        form.addRow(buttons)
        self.model_name = QLineEdit()
        self.model_name.setToolTip("Name shown in the Cameras panel and on the feeds")
        self.model_name.editingFinished.connect(self._set_name)
        form.addRow("Name", self.model_name)
        self.classes = QLineEdit()
        self.classes.setToolTip("Class names in the model's order, comma-separated")
        self.classes.editingFinished.connect(self._set_classes)
        form.addRow("Classes", self.classes)
        self.model_threshold = QDoubleSpinBox()
        self.model_threshold.setRange(0.05, 0.95)
        self.model_threshold.setSingleStep(0.05)
        self.model_threshold.setToolTip("Minimum confidence for a detection to be shown")
        self.model_threshold.valueChanged.connect(lambda v: self._model() and self._model().update(threshold=v))
        form.addRow("Threshold", self.model_threshold)
        hint = QLabel("Display only. Pick a model for a camera in the Cameras panel.")
        hint.setWordWrap(True)
        hint.setEnabled(False)
        form.addRow(hint)
        self.model_list.currentRowChanged.connect(self._show_model)
        self._show_model(self.model_list.currentRow())
        vision_page.addWidget(box)
        vision_page.addStretch(1)

        box, form = section("Grid images")
        self.labels = QCheckBox("Show camera names")
        self.labels.setChecked(cfg["show_labels_in_screenshots"])
        form.addRow("", self.labels)
        self.adaptive = QCheckBox("Portrait cells for rotated cameras")
        self.adaptive.setChecked(cfg["adaptive_resolution"])
        form.addRow("", self.adaptive)
        right.addWidget(box)

        left.addStretch(1)
        right.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # as big as the content, but never taller than the screen: OK/Cancel always visible
        avail = (parent.screen() if parent else QApplication.primaryScreen()).availableGeometry()
        want = QSize(max(p.sizeHint().width() for p in pages) + 60,
                     max(p.sizeHint().height() for p in pages) + tabs.tabBar().sizeHint().height()
                     + buttons.sizeHint().height() + 70)  # + margins, spacing, tab frame
        self.resize(min(max(want.width(), 860), int(avail.width() * 0.95)), min(want.height(), int(avail.height() * 0.9)))

    def _fill_cameras(self):
        """Connected cameras (live thumbnail, status), then known ones that are unplugged."""
        main = self.parent()
        rows = [(f.camera.label, dev, f.camera) for dev, f in getattr(main, "feeds", {}).items()]
        rows += [(st.get("name", "?"), dev, None) for dev, st in getattr(main, "saved_cams", {}).items()
                 if dev not in self.forgotten]
        t = self.cam_table
        if [(dev, cam is None) for _, dev, cam in rows] != self._shown_rows:  # (un)plugged or forgotten
            self._shown_rows = [(dev, cam is None) for _, dev, cam in rows]
            t.clearContents()
            t.setRowCount(len(rows))
            for r, (_, dev, cam) in enumerate(rows):
                for c in range(4):
                    item = QTableWidgetItem()
                    if cam is None:
                        item.setForeground(Qt.gray)
                    t.setItem(r, c, item)
                t.item(r, 2).setText(source_label(dev) or "—")
                t.item(r, 2).setToolTip(dev)
        for r, (name, dev, cam) in enumerate(rows):
            status, thumb = "Not connected", QIcon()
            if cam is not None:
                frame, preview = cam.frame, cam.preview
                status = cam.status or (f"● {frame.shape[1]}×{frame.shape[0]} · {cam.fps:.0f} fps"
                                        if frame is not None else "")
                if cam.ping is not None:
                    status += f" · {ping_text(cam.ping)}"
                if preview is not None:
                    thumb = QIcon(QPixmap.fromImage(preview[0]).scaled(96, 54, Qt.KeepAspectRatio,
                                                                       Qt.SmoothTransformation))
            t.item(r, 0).setIcon(thumb)
            t.item(r, 1).setText(name)
            t.item(r, 3).setText(status)

    def _selected_unplugged(self):
        rows = {i.row() for i in self.cam_table.selectedIndexes()}
        return [self._shown_rows[r][0] for r in rows if self._shown_rows[r][1]]

    def _selection_changed(self):
        self.forget.setEnabled(bool(self._selected_unplugged()))

    def _forget_selected(self):
        self.forgotten.update(self._selected_unplugged())
        self._fill_cameras()
        self._selection_changed()

    def _model(self):
        row = self.model_list.currentRow()
        return self.models[row] if 0 <= row < len(self.models) else None

    def _show_model(self, _row):
        m = self._model()
        for w in (self.model_name, self.classes, self.model_threshold):
            w.setEnabled(m is not None)
        self.model_name.setText(m["name"] if m else "")
        self.classes.setText(", ".join(m["classes"]) if m else "")
        self.model_threshold.blockSignals(True)
        self.model_threshold.setValue(m["threshold"] if m else 0.5)
        self.model_threshold.blockSignals(False)

    def _set_name(self):
        m = self._model()
        if m is None:
            return
        name = self.model_name.text().strip()
        if name == m["name"]:
            return
        if not name or any(o is not m and o["name"] == name for o in self.models):
            self.model_name.setText(m["name"])
            QMessageBox.warning(self, "Name", "Give the model a name that no other model has.")
            return
        m["name"] = name
        self.model_list.currentItem().setText(name)

    def renamed(self):
        """{old name: new name} of the models renamed in this dialog (cameras follow them)."""
        return {old: m["name"] for m, old in self._original
                if any(m is o for o in self.models) and m["name"] != old}

    def _set_classes(self):
        m = self._model()
        if m is None:
            return
        names = [n.strip() for n in self.classes.text().split(",") if n.strip()]
        if names == m["classes"]:
            return
        if len(names) != len(m["classes"]):
            self.classes.setText(", ".join(m["classes"]))
            QMessageBox.warning(self, "Classes", f"This model has {len(m['classes'])} classes: "
                                                 f"give {len(m['classes'])} names, comma-separated.")
            return
        m["classes"] = names

    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import a vision model", "", "ONNX models (*.onnx)")
        if path:
            self.add_model(path)

    def add_model(self, path):
        from vision import import_model  # loaded on first use: keeps onnxruntime out of startup
        taken = [m["name"] for m in self.models] + [os.path.splitext(os.path.basename(f))[0] for f in self.removed]
        try:
            entry = import_model(path, self.models_dir, taken)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Vision model", f"Cannot import this model:\n{e}")
            return
        self.models.append(entry)
        self.imported.append(os.path.join(self.models_dir, entry["file"]))
        self.model_list.addItem(entry["name"])
        self.model_list.setCurrentRow(len(self.models) - 1)

    def remove_model(self):
        row = self.model_list.currentRow()
        if row < 0:
            return
        entry = self.models.pop(row)
        self.removed.append(os.path.join(self.models_dir, entry["file"]))
        self.model_list.takeItem(row)

    def done(self, result):
        for path in self.removed if result else self.imported:  # recoverable, like recordings
            if os.path.exists(path):
                QFile.moveToTrash(path)
        super().done(result)

    def _split_toggled(self, on, warn=True):
        self.segment.setEnabled(on)
        self.split_warning.setVisible(not on)
        if warn and not on:
            QMessageBox.warning(
                self, "Single video file",
                "Without splitting, each video is one file that only becomes readable when the recording "
                "stops normally.\n\nIf the application crashes, the computer loses power or the disk gets "
                "full, the WHOLE recording is lost.\n\nWith splitting, you lose at most the last part.")

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def values(self):
        return {"output_folder": self.folder.text().strip(), "timelapse_interval": self.interval.value(),
                "timelapse_per_camera": bool(self.tl_mode.currentIndex()), "video_fps": self.fps.value(),
                "video_per_camera": bool(self.video_mode.currentIndex()),
                "video_motion_only": self.motion.isChecked(), "video_motion_threshold": self.threshold.value(),
                "video_timestamp": self.timestamp.isChecked(), "video_split": self.split.isChecked(),
                "video_segment_minutes": self.segment.value(),
                "show_labels_in_screenshots": self.labels.isChecked(),
                "adaptive_resolution": self.adaptive.isChecked(), "show_info_bar": self.info_bar.isChecked(),
                "timelapse_duration": self.tl_duration.value(), "video_duration": self.video_duration.value(),
                "models": self.models,
                "stream_urls": list(dict.fromkeys(u.strip() for u in self.stream_urls.toPlainText().splitlines()
                                                  if u.strip()))}
