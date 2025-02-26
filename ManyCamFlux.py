import sys
import cv2
import numpy as np
import os
import json
import subprocess
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                             QHBoxLayout, QCheckBox, QGridLayout, QPushButton, QSlider, QGroupBox, QDialog, QDialogButtonBox, QFileDialog, QLineEdit, QMessageBox, QComboBox)
from PyQt5.QtCore import QTimer, Qt, QDateTime
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QFont

def get_available_cameras(max_cameras=10):
    cams = []
    for i in range(max_cameras):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cams.append(i)
            cap.release()
    return cams

class GlobalControlDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Global Settings")
        self.layout = QVBoxLayout()
        self.parent_widget = parent

        # For each camera, add a groupbox of controls
        for idx in range(parent.num_cam):
            group = QGroupBox(f"Camera {idx}")
            group_layout = QVBoxLayout()

            # Camera name
            name_edit = QLineEdit(parent.cam_widgets[idx].name)
            name_edit.textChanged.connect(lambda text, i=idx: parent.set_camera_name(i, text))
            group_layout.addWidget(QLabel("Name"))
            group_layout.addWidget(name_edit)

            # Visibility checkbox
            vis_cb = QCheckBox("Visible")
            vis_cb.setChecked(parent.visible_flags[idx])
            vis_cb.stateChanged.connect(lambda state, i=idx: parent.toggle_camera(i, state))
            group_layout.addWidget(vis_cb)

            # Brightness slider
            brightness_slider = QSlider(Qt.Horizontal)
            brightness_slider.setRange(-100, 100)
            brightness_slider.setValue(parent.cam_widgets[idx].brightness)
            brightness_slider.valueChanged.connect(lambda value, i=idx: parent.set_brightness(i, value))
            group_layout.addWidget(QLabel("Brightness"))
            group_layout.addWidget(brightness_slider)

            # Contrast slider
            contrast_slider = QSlider(Qt.Horizontal)
            contrast_slider.setRange(-100, 100)
            contrast_slider.setValue(parent.cam_widgets[idx].contrast)
            contrast_slider.valueChanged.connect(lambda value, i=idx: parent.set_contrast(i, value))
            group_layout.addWidget(QLabel("Contrast"))
            group_layout.addWidget(contrast_slider)

            # Rotation buttons
            rotate_layout = QHBoxLayout()
            rotate_left = QPushButton("⟲")
            rotate_left.clicked.connect(lambda _, i=idx: parent.rotate_camera(i, -90))
            rotate_right = QPushButton("⟳")
            rotate_right.clicked.connect(lambda _, i=idx: parent.rotate_camera(i, 90))
            rotate_layout.addWidget(rotate_left)
            rotate_layout.addWidget(rotate_right)
            group_layout.addWidget(QLabel("Rotation"))
            group_layout.addLayout(rotate_layout)

            group.setLayout(group_layout)
            self.layout.addWidget(group)

        # Buttons to save and load configurations
        save_button = QPushButton("Save")
        save_button.clicked.connect(parent.save_config)
        import_button = QPushButton("Import")
        import_button.clicked.connect(parent.load_config)
        self.layout.addWidget(save_button)
        self.layout.addWidget(import_button)

        # Standard dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        self.layout.addWidget(buttons)
        self.setLayout(self.layout)

class ScreenshotDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Screenshot Settings")
        self.layout = QVBoxLayout()
        self.parent_widget = parent

        # Save folder selection
        self.save_folder_label = QLabel("Save Folder:")
        self.save_folder_edit = QLineEdit()
        self.save_folder_button = QPushButton("Choose...")
        self.save_folder_button.clicked.connect(self.choose_save_folder)
        self.layout.addWidget(self.save_folder_label)
        self.layout.addWidget(self.save_folder_edit)
        self.layout.addWidget(self.save_folder_button)

        # Screenshot interval
        self.interval_label = QLabel("Screenshot Interval (seconds):")
        self.interval_edit = QLineEdit()
        self.layout.addWidget(self.interval_label)
        self.layout.addWidget(self.interval_edit)

        # Start/Stop buttons
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_screenshot)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_screenshot)
        self.layout.addWidget(self.start_button)
        self.layout.addWidget(self.stop_button)

        self.setLayout(self.layout)
        self.screenshot_timer = QTimer()
        self.screenshot_timer.timeout.connect(self.take_screenshot)

        # Set default save folder
        default_save_folder = os.path.join(os.path.expanduser("~"), "Pictures", "ManyCamFlux_images")
        self.save_folder_edit.setText(default_save_folder)

    def choose_save_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose Save Folder")
        if folder:
            self.save_folder_edit.setText(folder)

    def start_screenshot(self):
        interval_text = self.interval_edit.text()
        if not interval_text.isdigit() or int(interval_text) < 1:
            interval_text = "1"
            self.interval_edit.setText(interval_text)
        interval = int(interval_text) * 1000
        self.screenshot_timer.start(interval)
        save_folder = self.save_folder_edit.text()
        if os.path.exists(save_folder):
            subprocess.Popen(['explorer', save_folder])
        QMessageBox.information(self, "Screenshot", "Recording started")

    def stop_screenshot(self):
        self.screenshot_timer.stop()
        QMessageBox.information(self, "Screenshot", "Recording stopped")

    def take_screenshot(self):
        save_folder = self.save_folder_edit.text()
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_hhmmss")
        filename = os.path.join(save_folder, f"screenshot_{timestamp}.jpg")
        self.parent_widget.take_screenshot(filename)

class CamFeedWidget(QLabel):
    def __init__(self, cap, parent=None, name=""):
        super().__init__(parent)
        self.cap = cap
        self.rotation_angle = 0
        self.brightness = 0
        self.contrast = 0
        self.name = name
        self.setMouseTracking(True)
        self.setScaledContents(True)
        self.fullscreen_mode = False
        self.parent_widget = parent
        self.setStyleSheet("background-color: lightblue;")
        self.setFont(QFont("Arial", 14, QFont.Bold))

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            frame = np.zeros((self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT), self.cap.get(cv2.CAP_PROP_FRAME_WIDTH), 3), dtype=np.uint8)
        frame = self.apply_rotation(frame)
        frame = self.apply_brightness_contrast(frame)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self.setPixmap(QPixmap.fromImage(qimg))

    def apply_rotation(self, frame):
        if self.rotation_angle == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation_angle == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif self.rotation_angle == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    def apply_brightness_contrast(self, frame):
        frame = cv2.convertScaleAbs(frame, alpha=1 + self.contrast / 100, beta=self.brightness)
        return frame

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QColor(255, 255, 255))
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRect(0, self.height() - 30, self.width(), 30)
        painter.drawText(10, self.height() - 10, self.name)

    def mouseDoubleClickEvent(self, event):
        # On double-click, toggle fullscreen mode
        if event.button() == Qt.LeftButton:
            if not self.fullscreen_mode:
                self.parent_widget.show_fullscreen(self)
            else:
                self.parent_widget.exit_fullscreen()

class CamFluxWidget(QWidget):
    def __init__(self, resolution=(640, 480)):
        super().__init__()
        self.setWindowTitle("Webcam Feeds - Qt")

        # Detect available cameras
        self.cam_indices = get_available_cameras()
        if not self.cam_indices:
            print("No cameras detected.")
            sys.exit()

        self.num_cam = len(self.cam_indices)
        self.caps = [cv2.VideoCapture(idx) for idx in self.cam_indices]

        # Set camera resolution
        for cap in self.caps:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])

        # Create a widget for each camera
        self.cam_widgets = [CamFeedWidget(cap, self, f"Camera {idx}") for idx, cap in enumerate(self.caps)]
        self.visible_flags = [True] * self.num_cam

        # Layout for feeds
        self.flux_layout = QGridLayout()

        main_layout = QVBoxLayout()
        self.flux_container = QWidget()
        self.flux_container.setLayout(self.flux_layout)
        main_layout.addWidget(self.flux_container)

        # Settings and Capture buttons side by side
        button_layout = QHBoxLayout()
        self.global_params_button = QPushButton("Settings")
        self.global_params_button.clicked.connect(self.show_global_params)
        button_layout.addWidget(self.global_params_button)

        self.screenshot_button = QPushButton("Capture")
        self.screenshot_button.clicked.connect(self.show_screenshot_dialog)
        button_layout.addWidget(self.screenshot_button)

        main_layout.addLayout(button_layout)

        # Back button to exit fullscreen mode
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.exit_fullscreen)
        self.back_button.setVisible(False)
        main_layout.addWidget(self.back_button)

        self.setLayout(main_layout)
        self.update_grid_layout()

        # Timer to refresh display
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frames)
        self.timer.start(30)

        # Load configuration at startup if it exists
        self.load_config_at_startup()

    def show_global_params(self):
        dialog = GlobalControlDialog(self)
        dialog.exec_()

    def show_screenshot_dialog(self):
        dialog = ScreenshotDialog(self)
        dialog.exec_()

    def set_camera_name(self, idx, name):
        self.cam_widgets[idx].name = name
        self.update_grid_layout()

    def set_brightness(self, idx, value):
        self.cam_widgets[idx].brightness = value

    def set_contrast(self, idx, value):
        self.cam_widgets[idx].contrast = value

    def rotate_camera(self, idx, angle):
        self.cam_widgets[idx].rotation_angle = (self.cam_widgets[idx].rotation_angle + angle) % 360

    def update_frames(self):
        for idx, widget in enumerate(self.cam_widgets):
            if self.visible_flags[idx]:
                widget.update_frame()

    def toggle_camera(self, idx, state):
        self.visible_flags[idx] = (state == Qt.Checked)
        self.cam_widgets[idx].setVisible(self.visible_flags[idx])
        self.update_grid_layout()

    def update_grid_layout(self):
        # Clear current layout
        while self.flux_layout.count():
            item = self.flux_layout.takeAt(0)
            if item.widget():
                self.flux_layout.removeWidget(item.widget())
        # Get visible widgets
        visible_widgets = [w for idx, w in enumerate(self.cam_widgets) if self.visible_flags[idx]]
        n = len(visible_widgets)
        if n == 0:
            return
        grid_size = int(np.ceil(np.sqrt(n)))
        for i, widget in enumerate(visible_widgets):
            row = i // grid_size
            col = i % grid_size
            self.flux_layout.addWidget(widget, row, col)

    def show_fullscreen(self, widget):
        widget.fullscreen_mode = True
        self.back_button.setVisible(True)
        # Hide other widgets
        for idx, w in enumerate(self.cam_widgets):
            if w != widget:
                w.hide()
        self.showFullScreen()
        self.update_grid_layout()

    def exit_fullscreen(self):
        self.back_button.setVisible(False)
        self.showNormal()
        for widget in self.cam_widgets:
            widget.fullscreen_mode = False
            widget.show()
        self.update_grid_layout()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.exit_fullscreen()

    def closeEvent(self, event):
        for cap in self.caps:
            cap.release()
        event.accept()

    def take_screenshot(self, filename):
        # Get visible widgets
        visible_widgets = [w for idx, w in enumerate(self.cam_widgets) if self.visible_flags[idx]]
        n = len(visible_widgets)
        if n == 0:
            return

        # Calculate grid size
        grid_size = int(np.ceil(np.sqrt(n)))
        rows = (n + grid_size - 1) // grid_size
        cols = min(n, grid_size)

        # Get the size of a single camera
        h, w, _ = visible_widgets[0].cap.read()[1].shape

        # Create an empty image to hold all visible cameras
        screenshot = np.zeros((rows * h, cols * w, 3), dtype=np.uint8)

        for idx, widget in enumerate(visible_widgets):
            ret, frame = widget.cap.read()
            if ret:
                frame = widget.apply_rotation(frame)
                frame = widget.apply_brightness_contrast(frame)
                frame = cv2.resize(frame, (w, h))  # Resize the image to match the target size
                row = idx // cols
                col = idx % cols
                screenshot[row*h:(row+1)*h, col*w:(col+1)*w] = frame

        cv2.imwrite(filename, screenshot)

    def save_config(self):
        config = {
            "cameras": []
        }
        for idx, widget in enumerate(self.cam_widgets):
            config["cameras"].append({
                "name": widget.name,
                "brightness": widget.brightness,
                "contrast": widget.contrast,
                "rotation_angle": widget.rotation_angle,
                "visible": self.visible_flags[idx]
            })
        config_path = os.path.join(os.path.dirname(__file__), "ManyCamFlux_config.json")
        with open(config_path, 'w') as config_file:
            json.dump(config, config_file, indent=4)
        QMessageBox.information(self, "Configuration", "Configuration saved")

    def load_config(self):
        config_path, _ = QFileDialog.getOpenFileName(self, "Open Configuration File", "", "JSON Files (*.json)")
        if config_path:
            with open(config_path, 'r') as config_file:
                config = json.load(config_file)
                for idx, cam_config in enumerate(config["cameras"]):
                    self.cam_widgets[idx].name = cam_config["name"]
                    self.cam_widgets[idx].brightness = cam_config["brightness"]
                    self.cam_widgets[idx].contrast = cam_config["contrast"]
                    self.cam_widgets[idx].rotation_angle = cam_config["rotation_angle"]
                    self.visible_flags[idx] = cam_config["visible"]
                self.update_grid_layout()
            QMessageBox.information(self, "Configuration", "Configuration loaded")

    def load_config_at_startup(self):
        config_path = os.path.join(os.path.dirname(__file__), "ManyCamFlux_config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r') as config_file:
                config = json.load(config_file)
                for idx, cam_config in enumerate(config["cameras"]):
                    self.cam_widgets[idx].name = cam_config["name"]
                    self.cam_widgets[idx].brightness = cam_config["brightness"]
                    self.cam_widgets[idx].contrast = cam_config["contrast"]
                    self.cam_widgets[idx].rotation_angle = cam_config["rotation_angle"]
                    self.visible_flags[idx] = cam_config["visible"]
                self.update_grid_layout()

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Choose resolution at startup
    resolution_dialog = QDialog()
    resolution_dialog.setWindowTitle("Choose Camera Resolution")
    layout = QVBoxLayout()
    resolution_label = QLabel("Select Camera Resolutions:")
    resolution_combo = QComboBox()
    resolution_combo.addItems(["640x480", "1280x720", "1600x1200"])
    layout.addWidget(resolution_label)
    layout.addWidget(resolution_combo)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(resolution_dialog.accept)
    buttons.rejected.connect(resolution_dialog.reject)
    layout.addWidget(buttons)
    resolution_dialog.setLayout(layout)

    if resolution_dialog.exec_() == QDialog.Accepted:
        resolution_text = resolution_combo.currentText()
        resolution = tuple(map(int, resolution_text.split('x')))
    else:
        sys.exit()

    widget = CamFluxWidget(resolution)
    widget.show()
    sys.exit(app.exec_())