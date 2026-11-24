import sys

import pytest

from camera import port_label, usb_port


def test_port_label():
    assert port_label("usb:PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(4)") == "4"
    assert port_label("usb:PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(4)#USB(2)") == "4.2"  # behind a hub
    assert port_label(r"@device:pnp:\\?\usb#vid_1&pid_2#3#{x}\global") == ""  # not port-identified
    assert port_label("sim:0") == ""


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
