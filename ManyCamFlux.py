import sys
from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout, QLabel, 
                           QComboBox, QDialogButtonBox, QSplashScreen, 
                           QCheckBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QFont

from camera_widgets import CamFluxWidget

if __name__ == "__main__":
    from utils import print_info, print_debug, print_success
    
    print_info("Starting ManyCamFlux application")
    app = QApplication(sys.argv)

    print_debug("Showing resolution selection dialog")
    resolution_dialog = QDialog()
    resolution_dialog.setWindowTitle("Choose Camera Resolution")
    layout = QVBoxLayout()
    resolution_label = QLabel("Select Camera Resolutions:")
    resolution_combo = QComboBox()
    resolution_combo.addItems([
        "640x480 (4:3) (VGA)",
        "854x480 (16:9) (FWVGA)",
        "1024x768 (4:3) (XGA)",
        "1280x720 (16:9) (HD)",
        "1600x1200 (4:3) (UXGA)",
        "1920x1080 (16:9) (FHD)"
    ])
    layout.addWidget(resolution_label)
    layout.addWidget(resolution_combo)
    
    keep_aspect_ratio_cb = QCheckBox("Keep aspect ratio of cameras")
    keep_aspect_ratio_cb.setChecked(True)  # Default checked
    layout.addWidget(keep_aspect_ratio_cb)
    
    adaptive_resolution_cb = QCheckBox("Keep camera ratio when taking screenshots (for camera rotations)")
    adaptive_resolution_cb.setChecked(True)  # Default checked
    layout.addWidget(adaptive_resolution_cb)
    
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(resolution_dialog.accept)
    buttons.rejected.connect(resolution_dialog.reject)
    layout.addWidget(buttons)
    resolution_dialog.setLayout(layout)

    if resolution_dialog.exec_() == QDialog.Accepted:
        resolution_text = resolution_combo.currentText()
        # Extract resolution from option
        resolution_numbers = resolution_text.split(' ')[0]  
        resolution = tuple(map(int, resolution_numbers.split('x')))
        print_debug(f"User selected resolution: {resolution_numbers} - (Option selected : {resolution_text})")
        
        keep_aspect_ratio = keep_aspect_ratio_cb.isChecked()
        print_debug(f"Keep aspect ratio: {keep_aspect_ratio}")
        
        print_debug("Showing loading screen")
        splash_pix = QPixmap(400, 200)
        splash_pix.fill(Qt.lightGray)
        splash = QSplashScreen(splash_pix)
        
        font = QFont("Arial", 16, QFont.Bold)
        splash.setFont(font)
        splash.showMessage("Loading cameras...", Qt.AlignCenter, Qt.black)
        
        splash.show()
        app.processEvents() 
        
        print_debug("Initializing main application")
        adaptive_resolution = adaptive_resolution_cb.isChecked()
        print_debug(f"Adaptive resolution: {adaptive_resolution}")
        widget = CamFluxWidget(resolution, keep_aspect_ratio, adaptive_resolution)
        
        print_debug("Initialization complete, showing main window")
        splash.finish(widget)
        widget.show()
        print_success("Application started successfully")
    else:
        print_debug("User cancelled resolution selection, exiting")
        sys.exit()

    sys.exit(app.exec_())