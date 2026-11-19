# ManyCamFlux

PyQt5 + OpenCV desktop app showing many webcams in one grid, with snapshots, timelapse and video recording. Windows is the main target.

Version: `utils.VERSION` (2.0), shown by Help (F1) and `--version`.

## Run / test
- `python ManyCamFlux.py`, or `python ManyCamFlux.py --simulate N` to add N synthetic 30 fps cameras (`camera.SimulatedCapture`, device id `sim:<n>`). Changing `camera.SIMULATED` at runtime exercises the hot-swap path.
- `python -m pytest -q tests` covers the pure image helpers in `imaging.py`.
- For a manual or scripted run that must leave the user's real data alone, set `USERPROFILE` (Windows) / `HOME` to a temp folder. Config lives in `~/Documents/ManyCamFlux/`, output in `~/Pictures/ManyCamFlux/`, and the config is saved on exit.

## Architecture
- `ManyCamFlux.py`: entry point, dark theme, splash. `cv2`/`numpy` are imported only once the splash is on screen (fast perceived launch). Keep heavy imports out of this file.
- `camera.py`: `Camera` is a `threading.Thread`, one per physical camera. It reads, adjusts (`imaging.adjust`) and builds a display-sized `QImage` preview. The GUI exchanges data with it only through plain attribute swaps (atomic under the GIL), without locks. Qt widgets are touched from the GUI thread only.
- `camera_widgets.py`: `CamFluxWidget` (QMainWindow) holds `feeds: {device_id: CamFeedWidget}`. A 33 ms timer repaints the feeds that got a new frame. A 2 s timer (`sync_cameras`) does the hot-swap.
- `recorder.py`: `Timelapse` (QTimer), `VideoRecorder` (a sampling thread feeding one `_Encoder` thread per file; a grid video is capped at 1920 px wide to stay real time; files split into parts; optional motion cut with `imaging.MotionDetector` + post-roll) and `RenderJob` (timelapse to video, shown as a progress bar in the status bar). Images are written by a small thread pool (`save_async`). Each session folder gets a `frames.csv` with one row per camera per saved frame, including the camera's source `frame_id`, so repeated or skipped ids show duplicated or dropped frames.
- `dialogs.py`: `CameraPanel` (dock, applies changes live) and `CaptureSettingsDialog`.
- `recordings.py`: `RecordingsDialog` (imported on first use). `find_tracks` groups video parts (`<stem>_001.mp4`, `_002`...) and image sequences (`<prefix>_000001.jpg`); `TrackSource` plays a track as one timeline; `load_times` maps each frame to its capture time from `frames.csv` (in a thread: a 24 h log has millions of rows).
- Icons are SVG files in `assets/icons/` (light stroke `#e1e3e7` for the dark theme), loaded with `utils.icon(name)`.

## Gotchas
- PyQt5 aborts the whole process on an exception raised in a slot, with no traceback. `ManyCamFlux.main` installs `sys.excepthook` to log instead; a test script that skips `main()` crashes silently (exit 127), so set `PYTHONIOENCODING=utf-8` there because status texts contain `●`.
- Cameras are identified by the Qt `QCameraInfo.deviceName()`. The OpenCV index is the camera's position in that list (DirectShow uses the same order on Windows), and it shifts when another camera is unplugged, so `sync_cameras` refreshes `camera.index`.
- With DirectShow, set the MJPG FOURCC **after** the width/height, or it is ignored (720p drops from 30 to 10 fps).
- Native resolution = what the driver picks for an impossible 10000x10000 request (`open_capture(probe=True)`, once per camera, ~1 s, no fps impact). `Camera.resolution_tag` compares it with the actual frame. Resolution lists never go above it: `camera.resolution_choices` / `clamp`, refreshed by `CamFluxWidget._check_natives` once natives arrive.
- Each camera has its own `resolution` (saved per camera); `cfg["resolution"]` is the toolbar default applied to all. Grid images use the largest frame as cell size.
- A rich-text `QLabel` inside a custom dock title bar swallows the mouse press and breaks dock dragging: keep title-bar labels `WA_TransparentForMouseEvents`.
- Recording deletions go through `QFile.moveToTrash` (recoverable). Session folders keep their `<kind>_<date>_<ms>` prefix when renamed (`recordings.renamed_path`).
- `cv2.imwrite` and `VideoWriter` fail on non-ASCII paths on Windows. Write images with `imaging.imwrite`.
- Config compatibility: camera entries without a `"device"` key come from old versions and are matched by order (`legacy_cams`). Keep the existing keys (`name`, `rotation_angle`, `show_labels_in_screenshots`, ...).
- PyInstaller: `pyinstaller -D -w --add-data "assets;assets" -i assets/icon.ico ManyCamFlux.py`. `PyQt5.QtMultimedia` must be bundled, or no camera is detected, and the Qt SVG plugins, or the icons are missing. A one-folder build (`-D`) starts much faster than `-F`, which unpacks itself on every launch.
