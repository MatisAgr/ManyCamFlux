import sys
from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout, QLabel, 
                           QComboBox, QDialogButtonBox, QSplashScreen)
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
        print_debug(f"User selected resolution: {resolution_text}")
        
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
        widget = CamFluxWidget(resolution)
        
        print_debug("Initialization complete, showing main window")
        splash.finish(widget)
        widget.show()
        print_success("Application started successfully")
    else:
        print_debug("User cancelled resolution selection, exiting")
        sys.exit()

    sys.exit(app.exec_())