import cv2

def get_available_cameras(max_cameras=10):
    """Detects available cameras on the system"""
    cams = []
    for i in range(max_cameras):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cams.append(i)
            cap.release()
    return cams

# ANSI COLORS for terminal output
class Colors:
    RESET = "\033[0m"
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"

def color_print(message, color=Colors.WHITE, bold=False, underline=False):
    """
    Prints a colored message to the console
    
    Args:
        message (str): The message to display
        color (str): ANSI color code (constant from Colors class)
        bold (bool): If True, text will be bold
        underline (bool): If True, text will be underlined
    """
    format_str = color
    if bold:
        format_str = Colors.BOLD + format_str
    if underline:
        format_str = Colors.UNDERLINE + format_str
    
    print(f"{format_str}{message}{Colors.RESET}")

# Helper functions for different message types
def print_error(message):
    color_print(f"[ERROR] {message}", Colors.RED, bold=True)

def print_warning(message):
    color_print(f"[WARNING] {message}", Colors.YELLOW)

def print_success(message):
    color_print(f"[SUCCESS] {message}", Colors.GREEN)

def print_info(message):
    color_print(f"[INFO] {message}", Colors.BLUE)

def print_debug(message):
    color_print(f"[DEBUG] {message}", Colors.CYAN)