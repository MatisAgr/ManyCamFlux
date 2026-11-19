from PyQt5.QtCore import QRegularExpression, Qt
from PyQt5.QtGui import QRegularExpressionValidator
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from camera import clamp, resolution_choices
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
        if cam is None:
            self.name.clear()
            self.rot_label.setText("")
            return
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(self.combo.findData(cam.device))
        self.combo.blockSignals(False)
        self.name.setText(cam.label)
        fill_resolutions(self.res, cam.native, cam.resolution)
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
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Capture settings")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        box, form = section("Output")
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(cfg["output_folder"])
        browse = QPushButton(icon("folder"), " Browse…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        form.addRow("Folder", folder_row)
        layout.addWidget(box)
        columns = QHBoxLayout()
        columns.setSpacing(12)
        left, right = QVBoxLayout(), QVBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns)

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
        self.video_duration = DurationField(cfg["video_duration"])
        form.addRow("Duration", self.video_duration)
        self.timestamp = QCheckBox("Burn date and time into the video")
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
        self.threshold.setDecimals(2)
        self.threshold.setSingleStep(0.1)
        self.threshold.setSuffix(" % of the image")
        self.threshold.setToolTip("Share of the image that must change to count as motion: lower = more sensitive")
        self.threshold.setValue(cfg["video_motion_threshold"])
        self.threshold.setEnabled(self.motion.isChecked())
        self.motion.toggled.connect(self.threshold.setEnabled)
        form.addRow("Motion threshold", self.threshold)
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
        left.addWidget(box)

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
        self.setMinimumWidth(860)

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
                "timelapse_duration": self.tl_duration.value(), "video_duration": self.video_duration.value()}
