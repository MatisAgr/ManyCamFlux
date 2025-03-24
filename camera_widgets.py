import cv2
import numpy as np
import os
import json
import subprocess
from PyQt5.QtWidgets import (QLabel, QWidget, QGridLayout, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QMessageBox, QFileDialog,
                            QMenu, QAction, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QCursor

class CamFeedWidget(QLabel):
    def __init__(self, cap, parent=None, name=""):
        super().__init__(parent)
        self.cap = cap
        self.rotation_angle = 0
        self.brightness = 0
        self.contrast = 0
        self.saturation = 0  # Nouvelle propriété pour la saturation
        self.name = name
        self.setMouseTracking(True)
        self.setScaledContents(True)
        self.fullscreen_mode = False
        self.parent_widget = parent
        self.setStyleSheet("background-color: lightblue;")
        self.setFont(QFont("Arial", 14, QFont.Bold))
        
        # Permettre le redimensionnement libre
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Menu contextuel pour les options de caméra
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, position):
        menu = QMenu(self)
        snapshot_action = QAction("Prendre un snapshot", self)
        snapshot_action.triggered.connect(self.take_snapshot)
        
        rotate_left = QAction("Rotation ⟲", self)
        rotate_left.triggered.connect(lambda: self.parent_widget.rotate_camera(
            self.parent_widget.cam_widgets.index(self), -90))
        
        rotate_right = QAction("Rotation ⟳", self)
        rotate_right.triggered.connect(lambda: self.parent_widget.rotate_camera(
            self.parent_widget.cam_widgets.index(self), 90))
        
        fullscreen_action = QAction("Plein écran", self)
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
            frame = self.apply_rotation(frame)
            frame = self.apply_brightness_contrast(frame)
            frame = self.apply_saturation(frame)  # Appliquer la saturation
            cv2.imwrite(filename, frame)
            
            # Notifier l'utilisateur
            QMessageBox.information(self, "Snapshot", f"Snapshot sauvegardé:\n{filename}")

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            frame = np.zeros((self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT), self.cap.get(cv2.CAP_PROP_FRAME_WIDTH), 3), dtype=np.uint8)
        frame = self.apply_rotation(frame)
        frame = self.apply_brightness_contrast(frame)
        frame = self.apply_saturation(frame)  # Appliquer la saturation
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
        self.setWindowTitle("ManyCamFlux")

        # Import is done here to avoid circular imports
        from utils import get_available_cameras
        from dialogs import GlobalControlDialog, ScreenshotDialog
        from PyQt5.QtCore import QDateTime  # Ajout pour l'horodatage des snapshots
        self.GlobalControlDialog = GlobalControlDialog
        self.ScreenshotDialog = ScreenshotDialog

        # Detect available cameras
        self.cam_indices = get_available_cameras()
        if not self.cam_indices:
            print("No cameras detected.")
            import sys
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
        self.flux_layout.setSpacing(5)  # Espacement entre les caméras

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
        
        # Bouton pour prendre un snapshot unique de toutes les caméras
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
        self.update_grid_layout()

        # Timer to refresh display
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frames)
        self.timer.start(30)

        # Load configuration at startup if it exists
        self.load_config_at_startup()
    
    def take_snapshot_all(self):
        # Créer un dossier de snapshots s'il n'existe pas
        snapshot_folder = os.path.join(os.path.expanduser("~"), "Pictures", "ManyCamFlux_snapshots")
        if not os.path.exists(snapshot_folder):
            os.makedirs(snapshot_folder)
        
        # Générer un nom de fichier avec horodatage
        from PyQt5.QtCore import QDateTime
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_hhmmss")
        filename = os.path.join(snapshot_folder, f"snapshot_all_{timestamp}.jpg")
        
        # Utiliser la fonction existante
        self.take_screenshot(filename)
        
        # Notifier l'utilisateur
        QMessageBox.information(self, "Snapshot", f"Snapshot de toutes les caméras sauvegardé:\n{filename}")
        
        # Ouvrir le dossier
        if os.path.exists(snapshot_folder):
            if os.name == 'nt':  # Windows
                subprocess.Popen(['explorer', snapshot_folder])

    def show_global_params(self):
        dialog = self.GlobalControlDialog(self)
        dialog.exec_()

    def show_screenshot_dialog(self):
        dialog = self.ScreenshotDialog(self)
        dialog.exec_()

    def set_camera_name(self, idx, name):
        self.cam_widgets[idx].name = name
        self.update_grid_layout()

    def set_brightness(self, idx, value):
        self.cam_widgets[idx].brightness = value

    def set_contrast(self, idx, value):
        self.cam_widgets[idx].contrast = value
        
    def set_saturation(self, idx, value):
        self.cam_widgets[idx].saturation = value

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

        # Get the size of a single camera
        h, w, _ = visible_widgets[0].cap.read()[1].shape

        # Create an empty image to hold all visible cameras
        screenshot = np.zeros((rows * h, cols * w, 3), dtype=np.uint8)

        for idx, widget in enumerate(visible_widgets):
            ret, frame = widget.cap.read()
            if ret:
                frame = widget.apply_rotation(frame)
                frame = widget.apply_brightness_contrast(frame)
                frame = widget.apply_saturation(frame)  # Appliquer la saturation
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
                "saturation": widget.saturation,  # Sauvegarde de la saturation
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
                    # Récupérer la saturation si elle existe dans le fichier de config
                    if "saturation" in cam_config:
                        self.cam_widgets[idx].saturation = cam_config["saturation"]
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
                    # Récupérer la saturation si elle existe dans le fichier de config
                    if "saturation" in cam_config:
                        self.cam_widgets[idx].saturation = cam_config["saturation"]
                    self.cam_widgets[idx].rotation_angle = cam_config["rotation_angle"]
                    self.visible_flags[idx] = cam_config["visible"]
                self.update_grid_layout()