import cv2

def get_available_cameras(max_cameras=10):
    """Détecte les caméras disponibles sur le système"""
    cams = []
    for i in range(max_cameras):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cams.append(i)
            cap.release()
    return cams