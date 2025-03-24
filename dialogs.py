import os
import subprocess
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QLineEdit, QPushButton, QGroupBox, QCheckBox, 
                            QSlider, QDialogButtonBox, QFileDialog, QMessageBox)
from PyQt5.QtCore import Qt, QTimer, QDateTime

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