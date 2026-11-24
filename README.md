![banner](https://github.com/user-attachments/assets/9316f617-90d5-4a45-8417-354397ed9515)

[![wakatime](https://wakatime.com/badge/user/a16f794f-b91d-4818-8dfc-d768ce605ece/project/94551038-ee66-499c-98e7-57493dd05c2d.svg)](https://wakatime.com/badge/user/a16f794f-b91d-4818-8dfc-d768ce605ece/project/94551038-ee66-499c-98e7-57493dd05c2d)

ManyCamFlux is a tiny project designed to manage multiple webcam feeds. It provides a simple interface to view, control, and capture screenshots from multiple cameras simultaneously.

> [!IMPORTANT]
> **🎉 ManyCamFlux 2.2 is out!** See the [**2.2 release**](https://github.com/MatisAgr/ManyCamFlux/releases/tag/2.2) patch note.
>
> 2.1 added object-detection models (RF-DETR, ONNX) tested live on your cameras, display only.
>
> 2.0 rewrote almost everything: threaded capture, hot-swap, video recording, timelapse, recordings browser, new camera panel... See the [**2.0 release**](https://github.com/MatisAgr/ManyCamFlux/releases/tag/2.0) patch note.
>
> Looking for the previous version? It is archived in the [Version-1.2-(OLD)](https://github.com/MatisAgr/ManyCamFlux/tree/Version-1.2-(OLD)) branch.

![ManyCamFlux main window with 6 simulated cameras, a vision model on two of them](docs/screenshots/main.png)

![Recordings browser](docs/screenshots/recordings.png)

![Settings](docs/screenshots/settings.png)

*Screenshots taken with simulated cameras (`--simulate 6`).*

## Features

- **Hot-swap**: plug or unplug cameras while the app runs; they appear or disappear automatically, and each camera gets its settings back when it is plugged in again. *Refresh* (`F5`) reconnects every camera if a feed ever gets stuck.
- **Cameras remembered by USB port**: a USB camera's name and settings belong to the port it is plugged into, so even identical cameras keep their settings whatever the plugging order. The panel shows each camera's port, and *Settings* › *Cameras* has a live **camera tester** (preview, name, port, status of every camera, plugged or not), where unplugged cameras can be forgotten.
- **Smooth live view**: each camera is captured in its own thread (MJPG when supported, so HD runs at full frame rate). Cameras open fast: settings are given at open time and each camera's native resolution is remembered. The grid adapts to the window size and camera ratio.
- **Camera panel**: name, visibility, resolution, brightness, contrast, saturation, rotation and horizontal/vertical mirror per camera, all applied live. Drag its title bar to detach it, or close it (`Ctrl+B`).
- **Resolution per camera**: the toolbar sets every camera at once, the panel sets one. Only resolutions up to each camera's native one are offered (detected automatically). The info bar under each view says whether the camera runs at its **native** (largest) resolution or is **downscaled** (and from what). The info bar can be hidden in *Settings*.
- **Snapshots**: one grid image of all cameras (`S`), or a single camera (right-click). A notice with a preview confirms it; click it to open the image.
- **Timelapse** (`T`): images at a regular interval (one grid image or one image per camera; *Settings* shows a small diagram of each mode).
- **Video recording** (`R`): one video per camera or one grid video, at the frame rate you choose.
- **Single camera**: right-click a camera for *Timelapse this camera only* or *Record this camera only* (one full-resolution file; the red dot marks the recorded camera).
- **Timed recordings**: a video or a timelapse can stop by itself after a duration (`hh:mm:ss`, more than 24 h allowed), set in *Settings*; the status bar shows the time left.
- **Long recordings (24 h and more)**: videos are split into parts (every 10 min by default), so a crash or power cut only loses the part being written; recording stops by itself before the disk is full (< 1 GB free). Splitting can be turned off (one file per camera), with a warning: an interrupted single file is lost.
- **Cut static scenes**: optional motion detection only keeps the frames where something moves (plus 2 s after), so a 24 h recording of a mostly still scene stays short. The date and time can be burned into the video, like a surveillance camera: the clock jumps show when nothing happened.
- **Recordings browser** (`Ctrl+L`): every session with a thumbnail, a built-in player (all parts as one timeline, speed up to ×64, frame by frame with ←/→) showing the real capture time of each frame, and *Render to video* for timelapses, with a progress bar at the bottom of the window. Recordings can be renamed (`F2`) and deleted (`Del`, to the recycle bin), or just one camera's track.
- **Frame tracking**: each timelapse/video session has a `frames.csv` with the frame number, timestamp, elapsed time and the source frame number of each camera (useful to spot dropped or duplicated frames).
- **Vision models (display only)**: import object-detection models (RF-DETR exported to ONNX) in *Settings*, then pick one per camera in the panel. Boxes are drawn on the live view, with the detections per second and, for each label found, its count and best confidence at the bottom; snapshots and videos stay raw. A model shared by several cameras is loaded once and serves them in turn, on the CPU (half the cores, so capture and recording keep their frame rate). Models can be renamed, and class names come from the model, a `classes.txt` next to it, or are edited in *Settings*.
- **Focus & fullscreen**: double-click a camera to show it alone, `F11` for fullscreen, `Esc` to go back.
- **Persistent settings**: saved automatically on exit (`~/Documents/ManyCamFlux/`), importable from a file.

## Download (Windows)

Two versions are available in the [latest release](https://github.com/MatisAgr/ManyCamFlux/releases/latest), nothing to install:

| File | How to use it | Startup |
|------|---------------|---------|
| `ManyCamFlux_2.2_windows.zip` (**recommended**) | Unzip it, then run `ManyCamFlux.exe` inside the folder. Keep the `_internal` folder next to the `.exe`. | Fast |
| `ManyCamFlux_2.2_portable.exe` | A single file: just run it. | Slower (it unpacks itself on every launch) |

## Requirements

To run ManyCamFlux, you need the following Python packages:

```plaintext
PyQt5
opencv-python
numpy
```

You can install these packages using the following command:

```sh
pip install -r requirements.txt
```

## Usage

1. **Clone the repository**:
    ```sh
    git clone https://github.com/MatisAgr/ManyCamFlux.git
    cd ManyCamFlux
    ```

2. **Run the application**:
    ```sh
    python ManyCamFlux.py
    ```

3. **Pick the resolution** in the toolbar (each camera uses the closest one it supports, shown at the bottom of its view).

4. **Adjust cameras** in the *Cameras* panel (`Ctrl+B` to show/hide it). Click a camera view to select it.

5. **Capture**: *Snapshot*, *Timelapse* and *Record* in the toolbar. Interval, frame rate, output mode and folder are in *Settings* (`Ctrl+,`).

### Shortcuts

| Key | Action |
|-----|--------|
| `S` | Snapshot of all cameras |
| `T` | Start/stop timelapse |
| `R` | Start/stop video recording |
| `Ctrl+L` | Recordings browser |
| `F1` | Help: version and shortcuts |
| `Ctrl+O` | Open the output folder |
| `F5` | Reconnect all cameras |
| `Ctrl+B` | Show/hide the Cameras panel |
| `F11` | Fullscreen |
| `Esc` | Leave focus / fullscreen |

## Notes

- Output goes to `~/Pictures/ManyCamFlux/` (`snapshots/`, `timelapse_<date>/`, `video_<date>/`). Keep the output folder path ASCII-only for videos (OpenCV limitation on Windows).
- Configuration is stored in `~/Documents/ManyCamFlux/`. Configs from older versions are still read.
- Tests: `python -m pytest -q tests`
- **No camera at hand?** `python ManyCamFlux.py --simulate 6` adds 6 simulated 30 fps cameras (moving target + frame number), handy to test the grid, recordings and frames.csv.

## Build with PyInstaller

To build your modifications of ManyCamFlux project into a standalone executable using PyInstaller, follow these steps:

1. **Install PyInstaller**:
    ```sh
    pip install pyinstaller
    ```

2. **Compile the project** (Windows):
    ```sh
    build.bat
    ```
    It builds both release files (about 3 min) into `.proj/release/`, named after `utils.VERSION`, and overwrites them if they exist:
    - `ManyCamFlux_<version>_windows.zip`: the one-folder build (`dist/ManyCamFlux/`) zipped, with `LICENSE`
    - `ManyCamFlux_<version>_portable.exe`: the single-file build (`LICENSE` is inside)

    It also replaces the old Visual C++ runtime bundled with PyQt5, which prevents the vision models from loading, with the build PC's newer one: build on a PC with an up-to-date Visual C++ runtime.
    - **Debug console**: remove `-w` in `build.bat`
    - **Mac/Linux**: `pyinstaller -D -w --add-data="assets:assets" --exclude-module PyQt6 --exclude-module torch ManyCamFlux.py`

📌 More details available at: [PyInstaller Documentation](https://pyinstaller.org/en/stable/usage.html)


3. **Run the executable**: the zip version needs its `_internal` folder next to `ManyCamFlux.exe` (unzip the whole folder); the portable `.exe` runs alone.

**Note:** `build.bat` calls `python -m PyInstaller`, so it works even when the `pyinstaller` command is not on the PATH.

*Further updates and adjustments will follow.*

## License

ManyCamFlux is free software under the [GNU GPL v3](LICENSE) (required by PyQt5, itself GPL v3)
