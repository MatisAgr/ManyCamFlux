import os
import subprocess
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QLineEdit, QPushButton, QGroupBox, QCheckBox, 
                            QSlider, QDialogButtonBox, QFileDialog, QMessageBox,
                            QComboBox, QSpinBox, QWidget, QTabWidget)
from PyQt5.QtCore import Qt, QTimer, QDateTime
from utils import print_debug, print_info, print_error, print_warning, print_success

class SliderWithValue(QWidget):
    """Custom widget that combines a slider and a numeric value"""
    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(parent)
        print_debug("Initializing SliderWithValue widget")
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Create the slider
        self.slider = QSlider(orientation)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(25)  # Fewer ticks
        
        # Create the value display
        self.value_display = QSpinBox()
        self.value_display.setButtonSymbols(QSpinBox.NoButtons)
        self.value_display.setFixedWidth(50)
        
        # Connect signals
        self.slider.valueChanged.connect(self.value_display.setValue)
        self.value_display.valueChanged.connect(self.slider.setValue)
        
        # Add widgets to the layout
        self.layout.addWidget(self.slider, 4)  # 80% of space
        self.layout.addWidget(self.value_display, 1)  # 20% of space
        
        self.setLayout(self.layout)

    def setRange(self, min_val, max_val):
        print_debug(f"Setting slider range: {min_val} to {max_val}")
        self.slider.setRange(min_val, max_val)
        self.value_display.setRange(min_val, max_val)
        
    def setValue(self, value):
        print_debug(f"Setting slider value to: {value}")
        self.slider.setValue(value)
        
    def value(self):
        return self.slider.value()
        
    def valueChanged(self):
        return self.slider.valueChanged

class GlobalControlDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        print_info("Opening Global Settings dialog")
        self.setWindowTitle("Global Settings")
        self.layout = QVBoxLayout()
        self.parent_widget = parent

        # Create tabs widget
        print_debug(f"Creating tab widget for {parent.num_cam} cameras")
        self.tab_widget = QTabWidget()
        
        # For each camera, create a tab
        for idx in range(parent.num_cam):
            print_debug(f"Configuring tab for camera {idx}")
            # Create a widget to contain controls for this camera
            camera_widget = QWidget()
            group_layout = QVBoxLayout(camera_widget)

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

            # Brightness slider with value
            print_debug(f"Setting up brightness slider for camera {idx}, current value: {parent.cam_widgets[idx].brightness}")
            brightness_slider = SliderWithValue(Qt.Horizontal)
            brightness_slider.setRange(-50, 50)  # Reduced scale
            brightness_slider.setValue(parent.cam_widgets[idx].brightness)
            brightness_slider.slider.valueChanged.connect(lambda value, i=idx: parent.set_brightness(i, value))
            group_layout.addWidget(QLabel("Brightness"))
            group_layout.addWidget(brightness_slider)

            # Contrast slider with value
            print_debug(f"Setting up contrast slider for camera {idx}, current value: {parent.cam_widgets[idx].contrast}")
            contrast_slider = SliderWithValue(Qt.Horizontal)
            contrast_slider.setRange(-50, 50)  # Reduced scale
            contrast_slider.setValue(parent.cam_widgets[idx].contrast)
            contrast_slider.slider.valueChanged.connect(lambda value, i=idx: parent.set_contrast(i, value))
            group_layout.addWidget(QLabel("Contrast"))
            group_layout.addWidget(contrast_slider)
            
            # Saturation slider with value
            current_saturation = getattr(parent.cam_widgets[idx], 'saturation', 0)
            print_debug(f"Setting up saturation slider for camera {idx}, current value: {current_saturation}")
            saturation_slider = SliderWithValue(Qt.Horizontal)
            saturation_slider.setRange(-50, 50)  # Reduced scale
            saturation_slider.setValue(current_saturation)
            saturation_slider.slider.valueChanged.connect(lambda value, i=idx: parent.set_saturation(i, value))
            group_layout.addWidget(QLabel("Saturation"))
            group_layout.addWidget(saturation_slider)

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

            # Add stretch at the end to prevent widget stretching
            group_layout.addStretch(1)
            
            # Add tab with camera name
            self.tab_widget.addTab(camera_widget, f"Camera {idx}")

        # Add tabs widget to main layout
        self.layout.addWidget(self.tab_widget)

        # Buttons to save and load configurations
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(parent.save_config)
        import_button = QPushButton("Import")
        import_button.clicked.connect(parent.load_config)
        button_layout.addWidget(save_button)
        button_layout.addWidget(import_button)
        self.layout.addLayout(button_layout)

        # Standard dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        self.layout.addWidget(buttons)
        self.setLayout(self.layout)
        print_debug("Global Settings dialog ready")

class ScreenshotDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        print_info("Opening Screenshot Settings dialog")
        self.setWindowTitle("Screenshot Settings")
        self.layout = QVBoxLayout()
        self.parent_widget = parent

        # Select save folder
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
        self.interval_edit.setText("5")  # Default value
        self.layout.addWidget(self.interval_label)
        self.layout.addWidget(self.interval_edit)
        
        # Checkbox for showing labels in screenshots
        self.show_labels_cb = QCheckBox("Show camera labels in screenshots")
        self.show_labels_cb.setChecked(parent.show_labels_in_screenshots)
        self.show_labels_cb.stateChanged.connect(self.toggle_labels)
        self.layout.addWidget(self.show_labels_cb)

        # Start/Stop buttons
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_screenshot)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_screenshot)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        self.layout.addLayout(button_layout)

        self.setLayout(self.layout)
        self.screenshot_timer = QTimer()
        self.screenshot_timer.timeout.connect(self.take_screenshot)

        # Set default save folder
        default_save_folder = os.path.join(os.path.expanduser("~"), "Pictures", "ManyCamFlux_images")
        self.save_folder_edit.setText(default_save_folder)
        print_debug(f"Default save folder set to: {default_save_folder}")
    
    def toggle_labels(self, state):
        self.parent_widget.show_labels_in_screenshots = (state == Qt.Checked)
        print_debug(f"Show labels in screenshots: {self.parent_widget.show_labels_in_screenshots}")

    def choose_save_folder(self):
        print_debug("User is selecting a save folder")
        folder = QFileDialog.getExistingDirectory(self, "Choose Save Folder")
        if folder:
            print_debug(f"User selected folder: {folder}")
            self.save_folder_edit.setText(folder)
        else:
            print_debug("Folder selection cancelled")

    def start_screenshot(self):
        interval_text = self.interval_edit.text()
        if not interval_text.isdigit() or int(interval_text) < 1:
            print_warning(f"Invalid interval entered: '{interval_text}', defaulting to 1 second")
            interval_text = "1"
            self.interval_edit.setText(interval_text)
        
        interval = int(interval_text) * 1000
        print_info(f"Starting screenshot recording with interval: {interval_text} seconds")
        self.screenshot_timer.start(interval)
        
        save_folder = self.save_folder_edit.text()
        if not os.path.exists(save_folder):
            print_debug(f"Creating screenshots directory: {save_folder}")
            os.makedirs(save_folder)
            
        if os.path.exists(save_folder):
            print_debug(f"Opening save folder: {save_folder}")
            try:
                if os.name == 'nt':  # Windows
                    subprocess.Popen(['explorer', save_folder])
                elif os.name == 'posix':  # macOS and Linux
                    subprocess.Popen(['open', save_folder])
            except Exception as e:
                print_error(f"Failed to open folder: {str(e)}")
                
        print_info("Screenshot recording started")
        QMessageBox.information(self, "Screenshot", "Recording started")

    def stop_screenshot(self):
        print_info("Stopping screenshot recording")
        self.screenshot_timer.stop()
        print_info("Screenshot recording stopped")
        QMessageBox.information(self, "Screenshot", "Recording stopped")

    def take_screenshot(self):
        save_folder = self.save_folder_edit.text()
        if not os.path.exists(save_folder):
            print_debug(f"Creating screenshots directory: {save_folder}")
            os.makedirs(save_folder)
            
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_hhmmss")
        filename = os.path.join(save_folder, f"screenshot_{timestamp}.jpg")
        print_success(f"Saved screenshot: {filename}")
        
        self.parent_widget.take_screenshot(filename)
