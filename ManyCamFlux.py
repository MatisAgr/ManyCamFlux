import sys
import os
from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout, QLabel, 
                           QComboBox, QDialogButtonBox, QSplashScreen, 
                           QCheckBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QFont, QIcon

from camera_widgets import CamFluxWidget

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller
    thx to : https://stackoverflow.com/questions/31836104/pyinstaller-and-onefile-how-to-include-an-image-in-the-exe-file"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

if __name__ == "__main__":
    from utils import print_info, print_debug, print_success, print_warning
    
    print_info("Starting ManyCamFlux application")
    app = QApplication(sys.argv)
    
    # Set application icon
    icon_path = resource_path(os.path.join("assets", "icon.ico"))
    if os.path.exists(icon_path):
        app_icon = QIcon(icon_path)
        app.setWindowIcon(app_icon)
        print_debug(f"Loaded application icon from {icon_path}")
    else:
        print_warning(f"Icon not found at {icon_path}, using default")

    print_debug("Showing resolution selection dialog")
    resolution_dialog = QDialog()
    resolution_dialog.setWindowTitle("Choose Camera Resolution")
    # Set icon for resolution dialog if available
    if os.path.exists(icon_path):
        resolution_dialog.setWindowIcon(QIcon(icon_path))
    
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
        
        print_debug("Showing loading screen with banner")
        
        # Check if banner exists and load it
        banner_path = resource_path(os.path.join("assets", "banner.png"))        
        if os.path.exists(banner_path):
            # Load the banner image
            original_pix = QPixmap(banner_path)
            
            # Resize the banner (reduce to 30% of original size)
            scale_factor = 0.2
            new_width = int(original_pix.width() * scale_factor)
            new_height = int(original_pix.height() * scale_factor)
            
            splash_pix = original_pix.scaled(new_width, new_height, 
                                             Qt.KeepAspectRatio, 
                                             Qt.SmoothTransformation)
            
            # Create splash screen with resized banner
            splash = QSplashScreen(splash_pix)
            print_debug(f"Loaded and scaled banner from {banner_path} ({new_width}x{new_height})")
        else:
            # Fallback to gray background if banner not found
            print_warning(f"Banner not found at {banner_path}, using default")
            splash_pix = QPixmap(400, 160)  # Smaller default size too
            splash_pix.fill(Qt.black)
            splash = QSplashScreen(splash_pix)
        
        font = QFont("Arial", 16, QFont.Bold)
        splash.setFont(font)
        
        # Display message over the banner
        splash.showMessage("Loading cameras...", Qt.AlignBottom | Qt.AlignCenter, Qt.white)
        
        splash.show()
        app.processEvents() 
        
        print_debug("Initializing main application")
        adaptive_resolution = adaptive_resolution_cb.isChecked()
        print_debug(f"Adaptive resolution: {adaptive_resolution}")
        widget = CamFluxWidget(resolution, keep_aspect_ratio, adaptive_resolution)
        
        # Set the application icon for the main window too
        if os.path.exists(icon_path):
            widget.setWindowIcon(QIcon(icon_path))
        
        print_debug("Initialization complete, showing main window")
        splash.finish(widget)
        widget.show()
        print_success("Application started successfully")
    else:
        print_debug("User cancelled resolution selection, exiting")
        sys.exit()

    sys.exit(app.exec_())