import cv2
import numpy as np
import os
import json
import subprocess
from PyQt5.QtWidgets import (QLabel, QWidget, QGridLayout, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QMessageBox, QFileDialog,
                            QMenu, QAction, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, QDateTime
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QCursor

from utils import get_available_cameras, print_info, print_debug, print_error, print_success, print_warning
from dialogs import GlobalControlDialog, ScreenshotDialog

class CamFeedWidget(QLabel):
    def __init__(self, cap, parent=None, name=""):
        super().__init__(parent)
        self.cap = cap
        self.rotation_angle = 0
        self.brightness = 0
        self.contrast = 0
        self.saturation = 0
        self.name = name
        
        self.original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.aspect_ratio = self.original_width / self.original_height
        
        self.setMouseTracking(True)
        
        self.setScaledContents(False)
        self.setAlignment(Qt.AlignCenter)
        
        self.fullscreen_mode = False
        self.parent_widget = parent
        self.setStyleSheet("background-color: lightblue;")
        self.setFont(QFont("Arial", 14, QFont.Bold))
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        self.setMinimumSize(160, 120)
        
        self.original_pixmap = None
        self.scaled_pixmap = None


    def show_context_menu(self, position):
        menu = QMenu(self)
        snapshot_action = QAction("Take Snapshot", self)
        snapshot_action.triggered.connect(self.take_snapshot)
        
        rotate_left = QAction("Rotate ⟲", self)
        rotate_left.triggered.connect(lambda: self.parent_widget.rotate_camera(
            self.parent_widget.cam_widgets.index(self), -90))
        
        rotate_right = QAction("Rotate ⟳", self)
        rotate_right.triggered.connect(lambda: self.parent_widget.rotate_camera(
            self.parent_widget.cam_widgets.index(self), 90))
        
        fullscreen_action = QAction("Full Screen", self)
        fullscreen_action.triggered.connect(lambda: self.parent_widget.show_fullscreen(self))
        
        menu.addAction(snapshot_action)
        menu.addSeparator()
        menu.addAction(rotate_left)
        menu.addAction(rotate_right)
        menu.addSeparator()
        menu.addAction(fullscreen_action)
        
        menu.exec_(QCursor.pos())

    def take_snapshot(self):
        # Créer un dossier de snapshots s'il n'existe pas
        snapshot_folder = os.path.join(os.path.expanduser("~"), "Pictures", "ManyCamFlux_snapshots")
        if not os.path.exists(snapshot_folder):
            os.makedirs(snapshot_folder)
        
        # Générer un nom de fichier avec horodatage
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_hhmmss")
        filename = os.path.join(snapshot_folder, f"snapshot_{self.name}_{timestamp}.jpg")
        
        # Capturer l'image
        ret, frame = self.cap.read()
        if ret:
            # Appliquer les ajustements
            frame = self.apply_rotation(frame)
            frame = self.apply_brightness_contrast(frame)
            frame = self.apply_saturation(frame)
            
            # Ajouter le nom de la caméra si l'option est activée
            if hasattr(self.parent_widget, 'show_labels_in_screenshots') and self.parent_widget.show_labels_in_screenshots:
                # Ajouter une barre de texte en bas
                text_bar = np.zeros((30, frame.shape[1], 3), dtype=np.uint8)
                frame = np.vstack([frame, text_bar])
                
                cv2.putText(
                    frame,
                    self.name,
                    (10, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2
                )
            
            # Sauvegarder l'image
            cv2.imwrite(filename, frame)
            
            # Notifier l'utilisateur
            QMessageBox.information(self, "Snapshot", f"Snapshot sauvegardé:\n{filename}")

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            frame = np.zeros((self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT), self.cap.get(cv2.CAP_PROP_FRAME_WIDTH), 3), dtype=np.uint8)
        frame = self.apply_rotation(frame)
        frame = self.apply_brightness_contrast(frame)
        frame = self.apply_saturation(frame)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        
        self.original_pixmap = QPixmap.fromImage(qimg)
        self.updateScaledPixmap()
        
    def updateScaledPixmap(self):
        if self.original_pixmap is None:
            return
            
        label_size = self.size()
        w, h = label_size.width(), label_size.height()
        
        if w == 0 or h == 0:
            return
            
        if self.parent_widget.keep_aspect_ratio:
            pixmap_ratio = self.original_pixmap.width() / self.original_pixmap.height()
            
            if w / h > pixmap_ratio:
                new_width = int(h * pixmap_ratio)
                new_height = h
            else:
                new_width = w
                new_height = int(w / pixmap_ratio)
            
            self.scaled_pixmap = self.original_pixmap.scaled(
                new_width, new_height, 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
        else:
            self.scaled_pixmap = self.original_pixmap.scaled(
                w, h,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            )
        
        self.setPixmap(self.scaled_pixmap)
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateScaledPixmap()

        
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
    
    def apply_saturation(self, frame):
        # Convertir en HSV pour modifier la saturation
        if self.saturation != 0:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype("float32")
            (h, s, v) = cv2.split(hsv)
            
            # Ajuster la saturation
            s = s * (1 + self.saturation / 100)
            s = np.clip(s, 0, 255)
            
            # Fusionner les canaux et reconvertir en BGR
            hsv = cv2.merge([h, s, v])
            frame = cv2.cvtColor(hsv.astype("uint8"), cv2.COLOR_HSV2BGR)
        return frame

    def paintEvent(self, event):
        if self.scaled_pixmap:
            painter = QPainter(self)
            
            if self.parent_widget.keep_aspect_ratio:
                x = (self.width() - self.scaled_pixmap.width()) // 2
                y = (self.height() - self.scaled_pixmap.height()) // 2
                
                painter.drawPixmap(x, y, self.scaled_pixmap)
            else:
                painter.drawPixmap(0, 0, self.width(), self.height(), self.scaled_pixmap)
            
            painter.setPen(QColor(255, 255, 255))
            painter.setBrush(QColor(0, 0, 0, 180))  # Fond semi-transparent
            painter.drawRect(0, self.height() - 30, self.width(), 30)
            painter.drawText(10, self.height() - 10, self.name)
            
            painter.end()
        else:
            super().paintEvent(event)

    def mouseDoubleClickEvent(self, event):
        # On double-click, toggle fullscreen mode
        if event.button() == Qt.LeftButton:
            if not self.fullscreen_mode:
                self.parent_widget.show_fullscreen(self)
            else:
                self.parent_widget.exit_fullscreen()

class CamFluxWidget(QWidget):
    def __init__(self, resolution=(640, 480), keep_aspect_ratio=False, adaptive_resolution=True):
        super().__init__()
        self.setWindowTitle("ManyCamFlux")
        
        self.keep_aspect_ratio = keep_aspect_ratio
        self.adaptive_resolution = adaptive_resolution
        print_info(f"Keep aspect ratio: {keep_aspect_ratio}, Adaptive resolution: {adaptive_resolution}")
        
        self.show_labels_in_screenshots = True
        
        self.resize_timer = QTimer()
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.update_grid_layout)

        self.selected_resolution = resolution

        self.GlobalControlDialog = GlobalControlDialog
        self.ScreenshotDialog = ScreenshotDialog
        
        print_info(f"Initializing ManyCamFlux with resolution {resolution}")

        # Detect available cameras
        print_debug("Scanning for available cameras...")
        self.cam_indices = get_available_cameras()
        if not self.cam_indices:
            print_error("No cameras detected. Application will exit.")
            import sys
            sys.exit()
        else:
            print_success(f"Found {len(self.cam_indices)} camera(s): {self.cam_indices}")

        self.num_cam = len(self.cam_indices)
        self.caps = [cv2.VideoCapture(idx) for idx in self.cam_indices]
        print_debug("Camera capture devices initialized")

        # Set camera resolution for capture (not display)
        for idx, cap in enumerate(self.caps):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
            print_debug(f"Camera {idx} resolution set to {resolution[0]}x{resolution[1]}")

        # Create a widget for each camera
        self.cam_widgets = [CamFeedWidget(cap, self, f"Camera {idx}") for idx, cap in enumerate(self.caps)]
        self.visible_flags = [True] * self.num_cam

        # Layout for feeds with stretch factors to permettre le redimensionnement
        self.flux_layout = QGridLayout()
        self.flux_layout.setSpacing(5)
        
        self.flux_container = QWidget()
        self.flux_container.setLayout(self.flux_layout)
        
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.flux_container, 1)

        # Settings and Capture buttons side by side
        button_layout = QHBoxLayout()
        self.global_params_button = QPushButton("Settings")
        self.global_params_button.clicked.connect(self.show_global_params)
        button_layout.addWidget(self.global_params_button)

        self.screenshot_button = QPushButton("Capture")
        self.screenshot_button.clicked.connect(self.show_screenshot_dialog)
        button_layout.addWidget(self.screenshot_button)
        
        self.snapshot_button = QPushButton("Snapshot")
        self.snapshot_button.clicked.connect(self.take_snapshot_all)
        button_layout.addWidget(self.snapshot_button)

        main_layout.addLayout(button_layout)

        # Back button to exit fullscreen mode
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.exit_fullscreen)
        self.back_button.setVisible(False)
        main_layout.addWidget(self.back_button)

        self.setLayout(main_layout)
        
        # Définir une taille de fenêtre par défaut généreuse
        self.resize(1024, 768)
        
        self.update_grid_layout()

        # Timer to refresh display
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frames)
        self.timer.start(30)

        # Load configuration at startup if it exists
        self.load_config_at_startup()
    
    def take_snapshot_all(self):
        
        snapshot_folder = os.path.join(os.path.expanduser("~"), "Pictures", "ManyCamFlux_snapshots")
        if not os.path.exists(snapshot_folder):
            os.makedirs(snapshot_folder)
            print_debug(f"Created snapshot directory: {snapshot_folder}")
        
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_hhmmss")
        filename = os.path.join(snapshot_folder, f"snapshot_all_{timestamp}.jpg")
        print_info(f"Taking snapshot of all cameras to {filename}")
        
        self.take_screenshot(filename)
        
        print_success(f"Snapshot saved: {filename}")
        QMessageBox.information(self, "Snapshot", f"Snapshot de toutes les caméras sauvegardé:\n{filename}")
        
        if os.path.exists(snapshot_folder):
            if os.name == 'nt':  # Windows
                print_debug(f"Opening folder in explorer: {snapshot_folder}")
                subprocess.Popen(['explorer', snapshot_folder])

    def show_global_params(self):
        dialog = self.GlobalControlDialog(self)
        dialog.exec_()

    def show_screenshot_dialog(self):
        dialog = self.ScreenshotDialog(self)
        dialog.exec_()

    def set_camera_name(self, idx, name):
        old_name = self.cam_widgets[idx].name
        self.cam_widgets[idx].name = name
        print_debug(f"Camera {idx} renamed: '{old_name}' -> '{name}'")
        self.update_grid_layout()

    def set_brightness(self, idx, value):
        self.cam_widgets[idx].brightness = value
        print_debug(f"Camera {idx} brightness set to {value}")

    def set_contrast(self, idx, value):
        self.cam_widgets[idx].contrast = value
        print_debug(f"Camera {idx} contrast set to {value}")
        
    def set_saturation(self, idx, value):
        self.cam_widgets[idx].saturation = value
        print_debug(f"Camera {idx} saturation set to {value}")

    def rotate_camera(self, idx, angle):
        old_angle = self.cam_widgets[idx].rotation_angle
        self.cam_widgets[idx].rotation_angle = (old_angle + angle) % 360
        print_debug(f"Camera {idx} rotated: {old_angle}° -> {self.cam_widgets[idx].rotation_angle}°")
        
    def update_frames(self):
        for idx, widget in enumerate(self.cam_widgets):
            if self.visible_flags[idx]:
                widget.update_frame()

    def toggle_camera(self, idx, state):
        self.visible_flags[idx] = (state == Qt.Checked)
        self.cam_widgets[idx].setVisible(self.visible_flags[idx])
        self.update_grid_layout()
        print_debug(f"Camera {idx} visibility set to {self.visible_flags[idx]}")

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
        
        container_width = self.flux_container.width()
        min_camera_width = 500
        
        max_columns = max(1, container_width // min_camera_width)
        
        rows = (n + max_columns - 1) // max_columns
        cols = min(n, max_columns)
        
        print_debug(f"Responsive layout: {rows} rows, {cols} columns for {n} cameras")
        
        for i, widget in enumerate(visible_widgets):
            row = i // cols
            col = i % cols
            self.flux_layout.addWidget(widget, row, col)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_grid_layout()
        self.resize_timer.start(200)

    def show_fullscreen(self, widget):
        widget.fullscreen_mode = True
        self.back_button.setVisible(True)
        # Hide other widgets
        for idx, w in enumerate(self.cam_widgets):
            if w != widget:
                w.hide()
        self.showFullScreen()
        self.update_grid_layout()
        print_debug(f"Entering fullscreen mode for {widget.name}")

    def exit_fullscreen(self):
        self.back_button.setVisible(False)
        self.showNormal()
        for widget in self.cam_widgets:
            widget.fullscreen_mode = False
            widget.show()
        self.update_grid_layout()
        print_debug("Exiting fullscreen mode")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.exit_fullscreen()

    def closeEvent(self, event):
        self.timer.stop()
        
        import time
        time.sleep(0.1)
        
        for cap in self.caps:
            if cap.isOpened():
                cap.release()
        
        for widget in self.cam_widgets:
            widget.setParent(None)
        self.cam_widgets.clear()
        
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
    
        # Base dimensions
        base_h, base_w = self.selected_resolution[1], self.selected_resolution[0]
        
        if self.adaptive_resolution == True:  # Condition inverted as requested
            # Adaptive cells for rotated cameras
            cell_dimensions = []
            for widget in visible_widgets:
                # Check if camera is rotated 90° or 270°
                rotated_90_or_270 = widget.rotation_angle in [90, 270]
                
                if rotated_90_or_270:
                    # For rotated cameras, invert width and height
                    cell_dimensions.append((base_h, base_w))
                else:
                    # For normal cameras, keep standard resolution
                    cell_dimensions.append((base_w, base_h))
            
            # Calculate max width for each column and max height for each row
            col_widths = [0] * cols
            row_heights = [0] * rows
            
            for i, (width, height) in enumerate(cell_dimensions):
                row = i // cols
                col = i % cols
                col_widths[col] = max(col_widths[col], width)
                row_heights[row] = max(row_heights[row], height)
            
            # Calculate final image dimensions
            total_width = sum(col_widths)
            total_height = sum(row_heights)
            
            # Create capture image with calculated dimensions
            screenshot = np.zeros((total_height, total_width, 3), dtype=np.uint8)
            
            # Initial position
            y_offset = 0
            
            # For each row
            for row in range(rows):
                x_offset = 0
                
                # For each column in this row
                for col in range(cols):
                    idx = row * cols + col
                    if idx >= len(visible_widgets):
                        break
                        
                    widget = visible_widgets[idx]
                    
                    # Calculate cell dimensions
                    cell_width = col_widths[col]
                    cell_height = row_heights[row]
                    
                    # Capture and process image
                    ret, frame = widget.cap.read()
                    if ret:
                        # Apply adjustments
                        frame = widget.apply_brightness_contrast(frame)
                        frame = widget.apply_saturation(frame)
                        
                        # Check if camera is rotated 90° or 270°
                        rotated_90_or_270 = widget.rotation_angle in [90, 270]
                        
                        if rotated_90_or_270:
                            # For rotated images, invert dimensions for resizing
                            frame = cv2.resize(frame, (cell_height, cell_width))
                        else:
                            frame = cv2.resize(frame, (cell_width, cell_height))
                        
                        # Apply rotation
                        frame = widget.apply_rotation(frame)
                        
                        # Add camera name if enabled
                        if self.show_labels_in_screenshots:
                            h, w = frame.shape[:2]
                            text_bar = np.zeros((30, w, 3), dtype=np.uint8)
                            frame = np.vstack([frame, text_bar])
                            
                            cv2.putText(
                                frame, 
                                widget.name, 
                                (10, frame.shape[0] - 10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 
                                0.7, 
                                (255, 255, 255), 
                                2
                            )
                        
                        # Place image in cell (centered)
                        h, w = frame.shape[:2]
                        
                        # Create temporary cell
                        temp_cell = np.zeros((cell_height, cell_width, 3), dtype=np.uint8)
                        
                        # Calculate centering offsets
                        offset_x = (cell_width - w) // 2
                        offset_y = (cell_height - h) // 2
                        
                        # Check dimensions
                        if offset_x >= 0 and offset_y >= 0:
                            # Place centered image
                            temp_cell[offset_y:offset_y+h, offset_x:offset_x+w] = frame
                        else:
                            # Resize if too large
                            scale_h = cell_height / h
                            scale_w = cell_width / w
                            scale = min(scale_h, scale_w)
                            
                            new_h = int(h * scale)
                            new_w = int(w * scale)
                            
                            resized_frame = cv2.resize(frame, (new_w, new_h))
                            
                            # Center resized image
                            new_offset_x = (cell_width - new_w) // 2
                            new_offset_y = (cell_height - new_h) // 2
                            
                            temp_cell[new_offset_y:new_offset_y+new_h, new_offset_x:new_offset_x+new_w] = resized_frame
                        
                        # Add cell to final image
                        screenshot[y_offset:y_offset+cell_height, x_offset:x_offset+cell_width] = temp_cell
                    
                    # Next column position
                    x_offset += cell_width
                
                # Next row position
                y_offset += row_heights[row]
        else:
            # Fixed cell size (non-adaptive)
            screenshot = np.zeros((rows * base_h, cols * base_w, 3), dtype=np.uint8)
            
            for idx, widget in enumerate(visible_widgets):
                ret, frame = widget.cap.read()
                if ret:
                    # Apply basic adjustments
                    frame = widget.apply_brightness_contrast(frame)
                    frame = widget.apply_saturation(frame)
                    
                    # Check rotation
                    rotated_90_or_270 = widget.rotation_angle in [90, 270]
                    
                    if rotated_90_or_270:
                        # Invert dimensions for rotated cameras
                        target_w, target_h = base_h, base_w
                        frame = cv2.resize(frame, (target_h, target_w))
                    else:
                        # Standard resize
                        frame = cv2.resize(frame, (base_w, base_h))
                    
                    # Apply rotation
                    frame = widget.apply_rotation(frame)
                    
                    # Add camera name if enabled
                    if self.show_labels_in_screenshots:
                        h, w = frame.shape[:2]
                        text_bar = np.zeros((30, w, 3), dtype=np.uint8)
                        frame = np.vstack([frame, text_bar])
                        
                        cv2.putText(
                            frame, 
                            widget.name, 
                            (10, frame.shape[0] - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 
                            0.7, 
                            (255, 255, 255), 
                            2
                        )
                    
                    # Fit to cell if needed
                    h, w = frame.shape[:2]
                    if h > base_h or w > base_w:
                        scale_h = base_h / h
                        scale_w = base_w / w
                        scale = min(scale_h, scale_w)
                        
                        new_h = int(h * scale)
                        new_w = int(w * scale)
                        frame = cv2.resize(frame, (new_w, new_h))
                    
                    # Create temporary cell
                    temp_frame = np.zeros((base_h, base_w, 3), dtype=np.uint8)
                    
                    # Center image in cell
                    offset_x = max(0, (base_w - frame.shape[1]) // 2)
                    offset_y = max(0, (base_h - frame.shape[0]) // 2)
                    
                    # Check bounds
                    frame_h, frame_w = frame.shape[:2]
                    place_h = min(frame_h, base_h - offset_y)
                    place_w = min(frame_w, base_w - offset_x)
                    
                    # Place in cell
                    temp_frame[offset_y:offset_y+place_h, offset_x:offset_x+place_w] = frame[:place_h, :place_w]
                    
                    # Add to final image
                    row = idx // cols
                    col = idx % cols
                    screenshot[row*base_h:(row+1)*base_h, col*base_w:(col+1)*base_w] = temp_frame
    
        cv2.imwrite(filename, screenshot)
        print_success(f"Screenshot saved to {filename}")

    def get_config_path(self):
        """Send the path to the configuration file."""
        config_dir = os.path.join(os.path.expanduser("~"), "Documents", "ManyCamFlux")
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
            print_debug(f"Created configuration directory: {config_dir}")
        return os.path.join(config_dir, "ManyCamFlux_config.json")

    def save_config(self):
        config = {
            "global_settings": {
                "show_labels_in_screenshots": self.show_labels_in_screenshots,
                "keep_aspect_ratio": self.keep_aspect_ratio,
                "adaptive_resolution": self.adaptive_resolution,
            },
            "cameras": []
        }
        for idx, widget in enumerate(self.cam_widgets):
            config["cameras"].append({
                "name": widget.name,
                "brightness": widget.brightness,
                "contrast": widget.contrast,
                "saturation": widget.saturation,
                "rotation_angle": widget.rotation_angle,
                "visible": self.visible_flags[idx]
            })
        
        config_path = self.get_config_path()
        print_info(f"Saving configuration to {config_path}")
        
        try:
            with open(config_path, 'w') as config_file:
                json.dump(config, config_file, indent=4)
            print_success("Configuration saved successfully")
            QMessageBox.information(self, "Configuration", "Configuration saved")
        except Exception as e:
            print_error(f"Failed to save configuration: {str(e)}")
            QMessageBox.warning(self, "Error", f"Failed to save configuration: {str(e)}")

    def load_config(self):
        
        config_path, _ = QFileDialog.getOpenFileName(self, "Open Configuration File", "", "JSON Files (*.json)")
        if not config_path:
            print_debug("Configuration loading cancelled by user")
            return
            
        print_info(f"Loading configuration from {config_path}")
        
        try:
            with open(config_path, 'r') as config_file:
                config = json.load(config_file)
                for idx, cam_config in enumerate(config["cameras"]):
                    if idx >= len(self.cam_widgets):
                        print_warning(f"Config has more cameras ({len(config['cameras'])}) than available ({len(self.cam_widgets)})")
                        break
                        
                    print_debug(f"Applying config to camera {idx}")
                    self.cam_widgets[idx].name = cam_config["name"]
                    self.cam_widgets[idx].brightness = cam_config["brightness"]
                    self.cam_widgets[idx].contrast = cam_config["contrast"]
                    if "saturation" in cam_config:
                        self.cam_widgets[idx].saturation = cam_config["saturation"]
                    self.cam_widgets[idx].rotation_angle = cam_config["rotation_angle"]
                    self.visible_flags[idx] = cam_config["visible"]
                
                self.update_grid_layout()
                print_success("Configuration loaded successfully")
                QMessageBox.information(self, "Configuration", "Configuration loaded")
        except Exception as e:
            print_error(f"Failed to load configuration: {str(e)}")
            QMessageBox.warning(self, "Error", f"Failed to load configuration: {str(e)}")

    def load_config_at_startup(self):
        config_path = self.get_config_path()        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as config_file:
                    config = json.load(config_file)
                    
                    if "global_settings" in config:
                        if "show_labels_in_screenshots" in config["global_settings"]:
                            self.show_labels_in_screenshots = config["global_settings"]["show_labels_in_screenshots"]
                            print_debug(f"Loaded show_labels_in_screenshots: {self.show_labels_in_screenshots}")
                        if "adaptive_resolution" in config["global_settings"]:
                            self.adaptive_resolution = config["global_settings"]["adaptive_resolution"]
                            print_debug(f"Loaded adaptive_resolution: {self.adaptive_resolution}")
                    
                    for idx, cam_config in enumerate(config["cameras"]):
                        if idx < len(self.cam_widgets):
                            self.cam_widgets[idx].name = cam_config["name"]
                            self.cam_widgets[idx].brightness = cam_config["brightness"]
                            self.cam_widgets[idx].contrast = cam_config["contrast"]
                            if "saturation" in cam_config:
                                self.cam_widgets[idx].saturation = cam_config["saturation"]
                            self.cam_widgets[idx].rotation_angle = cam_config["rotation_angle"]
                            self.visible_flags[idx] = cam_config["visible"]
                    self.update_grid_layout()
                    print_success("Configuration loaded successfully")
            except Exception as e:
                print_error(f"Failed to load configuration: {str(e)}")