"""Version, assets and coloured console logging."""
import os
import sys

from PyQt5.QtGui import QIcon

VERSION = "2.3"
REPO_URL = "https://github.com/MatisAgr/ManyCamFlux"


def hms(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"


def parse_hms(text):
    """'hh:mm:ss' (also 'mm:ss' or 'ss') -> seconds; 0 if empty or invalid."""
    try:
        parts = [int(p) for p in text.strip().split(":")]
    except ValueError:
        return 0
    if not 1 <= len(parts) <= 3 or any(p < 0 for p in parts):
        return 0
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def resource_path(relative_path):
    """Absolute path to a file in assets/, in dev and in a PyInstaller build (--add-data "assets;assets")."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", relative_path)


def icon(name):
    return QIcon(resource_path(os.path.join("icons", f"{name}.svg")))


RESET, RED, GREEN, YELLOW, BLUE, CYAN, BOLD = "\033[0m", "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[36m", "\033[1m"


def color_print(message, color):
    if sys.stdout is None:  # windowed PyInstaller build: no console
        return
    try:
        print(f"{color}{message}{RESET}", flush=True)
    except UnicodeEncodeError:  # console code page without the needed characters
        print(message.encode("ascii", "replace").decode(), flush=True)


def print_error(message):
    color_print(f"[ERROR] {message}", BOLD + RED)


def print_warning(message):
    color_print(f"[WARNING] {message}", YELLOW)


def print_success(message):
    color_print(f"[SUCCESS] {message}", GREEN)


def print_info(message):
    color_print(f"[INFO] {message}", BLUE)


def print_debug(message):
    color_print(f"[DEBUG] {message}", CYAN)
