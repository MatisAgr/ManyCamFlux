import sys

import pytest

from camera import port_label, usb_port


def test_port_label():
    assert port_label("usb:PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(4)") == "4"
    assert port_label("usb:PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(4)#USB(2)") == "4.2"  # behind a hub
    assert port_label(r"@device:pnp:\\?\usb#vid_1&pid_2#3#{x}\global") == ""  # not port-identified
    assert port_label("sim:0") == ""
    assert port_label("host:usb:PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(4)") == "4"  # served by a stream mirror


def test_source_label():
    from camera import source_label
    assert source_label("usb:PCIROOT(0)#USB(4)") == "4"
    assert source_label("host:usb:PCIROOT(0)#USB(4)") == "mirror · USB 4"
    assert source_label("http://192.168.1.20:8080/video") == "http://192.168.1.20:8080/video"
    assert source_label("sim:0") == ""


def test_network_cameras_next_to_usb_ones(monkeypatch):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import camera

    class Mirror(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps([{"Number": 1, "Id": "usb:PCIROOT(0)#USB(4)", "Name": "Cam A", "Stream": "/cam/1.mjpg"}])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    class Info:  # a local camera as QCameraInfo lists it
        def __init__(self, port):
            self.port = port

        def deviceName(self):
            return self.port

        def description(self):
            return "USB cam"

    server = HTTPServer(("127.0.0.1", 0), Mirror)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(camera.QCameraInfo, "availableCameras", lambda: [Info("PCIROOT(0)#USB(4)"), Info("PCIROOT(0)#USB(5)")])
    monkeypatch.setattr(camera, "usb_port", lambda name: name)
    monkeypatch.setattr(camera, "STREAM_URLS", [base + "/cams", "rtsp://10.0.0.9/live"])
    monkeypatch.setattr(camera, "_mirrors", {})
    expected = [("usb:PCIROOT(0)#USB(5)", "USB cam", 1, "PCIROOT(0)#USB(5)"),  # USB(4) is left to the mirror
                ("host:usb:PCIROOT(0)#USB(4)", "Cam A", base + "/cam/1.mjpg", "usb:PCIROOT(0)#USB(4)"),
                ("rtsp://10.0.0.9/live", "10.0.0.9", "rtsp://10.0.0.9/live", "rtsp://10.0.0.9/live")]
    assert camera.list_cameras() == expected
    server.shutdown()
    server.server_close()
    assert camera.list_cameras() == expected  # mirror down: last list kept, its feeds show UNAVAILABLE
    monkeypatch.setattr(camera, "STREAM_URLS", [])
    assert [c[0] for c in camera.list_cameras()] == ["usb:PCIROOT(0)#USB(4)", "usb:PCIROOT(0)#USB(5)"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows device tree")
def test_usb_port_unknown_device():
    assert usb_port(r"@device:pnp:\\?\usb#vid_ffff&pid_ffff&mi_00#9&dead&0&0000#{x}\global") is None
    assert usb_port("@device:sw:{860BB310-5D01-11D0-BD3B-00A0C911CE86}\\virtual") is None  # not USB


def test_native_resolution_kept_for_the_same_model_only():
    from camera import Camera
    saved = Camera("usb:x", "HD USB Camera", 0, (1280, 720))
    saved.native = (3264, 2448)
    same, other = Camera("usb:x", "HD USB Camera", 0, (1280, 720)), Camera("usb:x", "Other cam", 0, (1280, 720))
    same.apply_settings(saved.settings())
    other.apply_settings(saved.settings())
    assert same.native == (3264, 2448)
    assert other.native is None  # another model plugged into that port: probed again


def test_ping_of_a_network_camera():
    import socket
    import threading
    import time

    from camera import Camera, ping_text
    assert (ping_text(None), ping_text(0.4), ping_text(12.3)) == ("", "ping <1 ms", "ping 12 ms")
    server = socket.create_server(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{server.getsockname()[1]}/video"
    cam = Camera(url, "net", url, (640, 480))
    threading.Thread(target=cam._measure_ping, daemon=True).start()
    deadline = time.time() + 5
    while cam.ping is None and time.time() < deadline:
        time.sleep(0.05)
    assert cam.ping is not None and cam.ping < 1000
    server.close()
    cam.index = "http://127.0.0.1:1/video"  # nothing listens there: unreachable
    deadline = time.time() + 5
    while cam.ping is not None and time.time() < deadline:
        time.sleep(0.05)
    cam._halt.set()
    assert cam.ping is None


def test_mirror_stream_asks_the_chosen_size(monkeypatch):
    import camera
    opened = []

    class FakeCapture:
        def __init__(self, url, *args):
            opened.append(url)

        def isOpened(self):
            return True

    monkeypatch.setattr(camera.cv2, "VideoCapture", FakeCapture)
    camera.open_capture("host:usb:x", "http://127.0.0.1:8090/cam/1.mjpg", (640, 480))
    camera.open_capture("host:usb:x", "http://127.0.0.1:8090/cam/1.mjpg?q=50", (640, 480))
    camera.open_capture("http://10.0.0.9/video", "http://10.0.0.9/video", (640, 480))  # plain stream: left as is
    camera.open_capture("host:usb:x", "http://127.0.0.1:8090/cam/1.mjpg", (640, 480), max_fps=5)
    camera.open_capture("http://10.0.0.9/video", "http://10.0.0.9/video", (640, 480), max_fps=5)  # not a mirror: ignored
    assert opened == ["http://127.0.0.1:8090/cam/1.mjpg?w=640&h=480", "http://127.0.0.1:8090/cam/1.mjpg?q=50&w=640&h=480",
                      "http://10.0.0.9/video", "http://127.0.0.1:8090/cam/1.mjpg?w=640&h=480&fps=5", "http://10.0.0.9/video"]


def test_max_fps_saved_with_the_camera():
    from camera import FPS_CHOICES, Camera
    assert FPS_CHOICES[0][0] == 0  # "Max" first: the default, every frame of the stream
    saved = Camera("host:usb:x", "cam", "http://h/cam/1.mjpg", (1280, 720))
    saved.max_fps = 5
    again = Camera("host:usb:x", "cam", "http://h/cam/1.mjpg", (1280, 720))
    again.apply_settings(saved.settings())
    assert again.max_fps == 5
    again.apply_settings({})  # a config saved before this setting: max
    assert again.max_fps == 0
