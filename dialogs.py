import os
import subprocess
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QLineEdit, QPushButton, QGroupBox, QCheckBox, 
                            QSlider, QDialogButtonBox, QFileDialog, QMessageBox,
                            QComboBox, QSpinBox, QWidget, QTabWidget)
from PyQt5.QtCore import Qt, QTimer, QDateTime

class SliderWithValue(QWidget):
    """Widget personnalisé qui combine un slider et une valeur numérique"""
    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Créer le slider
        self.slider = QSlider(orientation)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(25)  # Moins de crans
        
        # Créer l'affichage de la valeur
        self.value_display = QSpinBox()
        self.value_display.setButtonSymbols(QSpinBox.NoButtons)
        self.value_display.setFixedWidth(50)
        
        # Connecter les signaux
        self.slider.valueChanged.connect(self.value_display.setValue)
        self.value_display.valueChanged.connect(self.slider.setValue)
        
        # Ajouter les widgets au layout
        self.layout.addWidget(self.slider, 4)  # 80% de l'espace
        self.layout.addWidget(self.value_display, 1)  # 20% de l'espace
        
        self.setLayout(self.layout)

    def setRange(self, min_val, max_val):
        self.slider.setRange(min_val, max_val)
        self.value_display.setRange(min_val, max_val)
        
    def setValue(self, value):
        self.slider.setValue(value)
        
    def value(self):
        return self.slider.value()
        
    def valueChanged(self):
        return self.slider.valueChanged

class GlobalControlDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Global Settings")
        self.layout = QVBoxLayout()
        self.parent_widget = parent

        # Création d'un widget d'onglets
        self.tab_widget = QTabWidget()
        
        # Pour chaque caméra, créer un onglet
        for idx in range(parent.num_cam):
            # Créer un widget pour contenir les contrôles de cette caméra
            camera_widget = QWidget()
            group_layout = QVBoxLayout(camera_widget)

            # Nom de la caméra
            name_edit = QLineEdit(parent.cam_widgets[idx].name)
            name_edit.textChanged.connect(lambda text, i=idx: parent.set_camera_name(i, text))
            group_layout.addWidget(QLabel("Name"))
            group_layout.addWidget(name_edit)

            # Case à cocher pour la visibilité
            vis_cb = QCheckBox("Visible")
            vis_cb.setChecked(parent.visible_flags[idx])
            vis_cb.stateChanged.connect(lambda state, i=idx: parent.toggle_camera(i, state))
            group_layout.addWidget(vis_cb)

            # Slider de luminosité avec valeur
            brightness_slider = SliderWithValue(Qt.Horizontal)
            brightness_slider.setRange(-50, 50)  # Réduire l'échelle
            brightness_slider.setValue(parent.cam_widgets[idx].brightness)
            brightness_slider.slider.valueChanged.connect(lambda value, i=idx: parent.set_brightness(i, value))
            group_layout.addWidget(QLabel("Brightness"))
            group_layout.addWidget(brightness_slider)

            # Slider de contraste avec valeur
            contrast_slider = SliderWithValue(Qt.Horizontal)
            contrast_slider.setRange(-50, 50)  # Réduire l'échelle
            contrast_slider.setValue(parent.cam_widgets[idx].contrast)
            contrast_slider.slider.valueChanged.connect(lambda value, i=idx: parent.set_contrast(i, value))
            group_layout.addWidget(QLabel("Contrast"))
            group_layout.addWidget(contrast_slider)
            
            # Slider de saturation avec valeur
            saturation_slider = SliderWithValue(Qt.Horizontal)
            saturation_slider.setRange(-50, 50)  # Échelle réduite
            saturation_slider.setValue(getattr(parent.cam_widgets[idx], 'saturation', 0))
            saturation_slider.slider.valueChanged.connect(lambda value, i=idx: parent.set_saturation(i, value))
            group_layout.addWidget(QLabel("Saturation"))
            group_layout.addWidget(saturation_slider)

            # Boutons de rotation
            rotate_layout = QHBoxLayout()
            rotate_left = QPushButton("⟲")
            rotate_left.clicked.connect(lambda _, i=idx: parent.rotate_camera(i, -90))
            rotate_right = QPushButton("⟳")
            rotate_right.clicked.connect(lambda _, i=idx: parent.rotate_camera(i, 90))
            rotate_layout.addWidget(rotate_left)
            rotate_layout.addWidget(rotate_right)
            group_layout.addWidget(QLabel("Rotation"))
            group_layout.addLayout(rotate_layout)

            # Ajouter un espace élastique à la fin pour éviter l'étirement
            group_layout.addStretch(1)
            
            # Ajouter l'onglet avec le nom de la caméra
            self.tab_widget.addTab(camera_widget, f"Camera {idx}")

        # Ajouter le widget d'onglets au layout principal
        self.layout.addWidget(self.tab_widget)

        # Boutons pour sauvegarder et charger les configurations
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(parent.save_config)
        import_button = QPushButton("Import")
        import_button.clicked.connect(parent.load_config)
        button_layout.addWidget(save_button)
        button_layout.addWidget(import_button)
        self.layout.addLayout(button_layout)

        # Boutons standard de dialogue
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

        # Sélection du dossier de sauvegarde
        self.save_folder_label = QLabel("Save Folder:")
        self.save_folder_edit = QLineEdit()
        self.save_folder_button = QPushButton("Choose...")
        self.save_folder_button.clicked.connect(self.choose_save_folder)
        self.layout.addWidget(self.save_folder_label)
        self.layout.addWidget(self.save_folder_edit)
        self.layout.addWidget(self.save_folder_button)

        # Intervalle entre les captures d'écran
        self.interval_label = QLabel("Screenshot Interval (seconds):")
        self.interval_edit = QLineEdit()
        self.interval_edit.setText("5")  # Valeur par défaut
        self.layout.addWidget(self.interval_label)
        self.layout.addWidget(self.interval_edit)

        # Boutons Start/Stop
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

        # Définir le dossier de sauvegarde par défaut
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
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)
        if os.path.exists(save_folder):
            if os.name == 'nt':  # Windows
                subprocess.Popen(['explorer', save_folder])
            elif os.name == 'posix':  # macOS et Linux
                subprocess.Popen(['open', save_folder])
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