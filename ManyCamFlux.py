import argparse
import os
import sys
import traceback

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QPalette, QPixmap
from PyQt5.QtWidgets import QApplication, QSplashScreen

from utils import VERSION, print_error, resource_path


def log_exception(kind, value, tb):
    # PyQt5 aborts the whole app on an exception in a slot unless an excepthook is set:
    # log it instead, so a bug never kills a running (24 h) recording
    print_error("".join(traceback.format_exception(kind, value, tb)))


def apply_dark_theme(app):
    app.setStyle("Fusion")
    window, base, text, accent = QColor(37, 38, 42), QColor(27, 28, 31), QColor(225, 227, 231), QColor(53, 132, 228)
    p = QPalette()
    for role, color in ((QPalette.Window, window), (QPalette.WindowText, text), (QPalette.Base, base),
                        (QPalette.AlternateBase, window), (QPalette.ToolTipBase, base), (QPalette.ToolTipText, text),
                        (QPalette.Text, text), (QPalette.Button, window), (QPalette.ButtonText, text),
                        (QPalette.Highlight, accent), (QPalette.HighlightedText, Qt.white), (QPalette.Link, accent)):
        p.setColor(role, color)
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, QColor(115, 117, 122))
    app.setPalette(p)
    check = resource_path(os.path.join("icons", "check.svg")).replace("\\", "/")
    app.setStyleSheet("""
        QToolBar { spacing: 4px; padding: 4px; border: none; }
        QToolBar QComboBox, QToolBar QCheckBox { margin: 0 4px; }
        QToolButton { padding: 5px 10px; border-radius: 6px; }
        QToolButton:hover { background: #3a3c41; }
        QToolButton:checked { background: #2d3f57; }
        QToolButton#rec:checked { background: #c0392b; color: white; }
        QComboBox { padding: 3px 8px; }
        QPushButton { padding: 5px 12px; }
        QPushButton:checked { background: #2d3f57; border: 1px solid #3584e4; border-radius: 3px; }
        QDockWidget::title { padding: 6px; }
        #dockTitle { background: #2b2d31; border-bottom: 1px solid #3a3c41; }
        #dockTitle:hover { background: #33363c; }
        QGroupBox { border: 1px solid #3a3c41; border-radius: 6px; margin-top: 16px; padding: 12px 8px 6px 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #8ab4f8; }
        QStatusBar QLabel { padding: 0 6px; }
        QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #6b6f76; border-radius: 3px;
                               background: #1b1c1f; }
        QCheckBox::indicator:hover { border-color: #8ab4f8; }
        QCheckBox::indicator:checked { background: #3584e4; border-color: #3584e4; image: url("CHECK"); }
        QCheckBox::indicator:disabled { border-color: #45484e; }
        QCheckBox::indicator:checked:disabled { background: #2d3f57; border-color: #2d3f57; }
    """.replace("CHECK", check))


def main():
    parser = argparse.ArgumentParser(description="View, capture and record many webcams at once.")
    parser.add_argument("--simulate", type=int, default=0, metavar="N",
                        help="add N simulated cameras (to test without hardware)")
    parser.add_argument("--version", action="version", version=f"ManyCamFlux {VERSION}")
    args, qt_args = parser.parse_known_args()
    sys.excepthook = log_exception

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1] + qt_args)
    app.setApplicationName("ManyCamFlux")
    app.setWindowIcon(QIcon(resource_path("icon.ico")))

    banner = QPixmap(resource_path("banner.png"))
    if banner.isNull():
        banner = QPixmap(480, 120)
        banner.fill(Qt.black)
    splash = QSplashScreen(banner.scaledToWidth(560, Qt.SmoothTransformation))
    splash.setFont(QFont("Segoe UI", 12, QFont.Bold))
    splash.showMessage("Loading…", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
    splash.show()
    app.processEvents()

    apply_dark_theme(app)
    # heavy imports (OpenCV, numpy) only once the splash is on screen
    import camera
    from camera_widgets import CamFluxWidget
    camera.SIMULATED = max(0, args.simulate)
    window = CamFluxWidget()
    window.show()
    splash.finish(window)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
