![banner](https://github.com/user-attachments/assets/9316f617-90d5-4a45-8417-354397ed9515)

ManyCamFlux is a tiny project designed to manage multiple webcam feeds. It provides a simple interface to view, control, and capture screenshots from multiple cameras simultaneously.

![screen](https://github.com/user-attachments/assets/65cdcf14-3797-47e3-b4d5-0242d7de8c7e)

## Features

- **Multiple Camera Support**: Automatically detects and displays feeds from multiple cameras.
- **Camera Controls**: Adjust brightness, contrast, saturation, and rotation for each camera feed.
- **Screenshot Capture**: Capture screenshots at regular intervals and save them to a specified folder.
- **Manual Snapshots**: Take instant snapshots of individual cameras or all cameras at once.
- **Configuration Management**: Save and load camera settings and configurations.
- **Persistent Settings**: Configuration is automatically saved to user's Documents folder.
- **Camera Rotation**: Rotate any camera view by 90°, 180°, or 270°.
- **Aspect Ratio Control**: Option to maintain camera aspect ratios during display and capture.
- **Adaptive Screenshots**: Maintain proper dimensions for rotated cameras in screenshot grid.

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

3. **Choose Camera Resolution**: On startup, you will be prompted to select the camera resolution.

4. **View and Control Feeds**: The main window will display the feeds from all detected cameras. Use the settings button to adjust camera parameters.

5. **Capture Screenshots**: Use the capture button to open the screenshot settings dialog and start capturing screenshots at regular intervals.

## Notes

- Ensure that your cameras are properly connected and recognized by your operating system.
- The default save folder for screenshots is `~/Pictures/ManyCamFlux_images`.
- Manual snapshots are saved in `~/Pictures/ManyCamFlux_snapshots`.
- Configuration files are stored in `~/Documents/ManyCamFlux/`.
- Cameras are adjusted to the size of the window, so they don't distort when captured.

## Build with PyInstaller

To build your modifications of ManyCamFlux project into a standalone executable using PyInstaller, follow these steps:

1. **Install PyInstaller**:
    ```sh
    pip install pyinstaller
    ```

2. **Compile the project**:
    ```sh
    pyinstaller --onefile -w -i .\assets\icon.ico .\ManyCamFlux.py
    ```
    or for debug :
    ```sh
    pyinstaller --onefile -i .\assets\icon.ico .\ManyCamFlux.py
    ```

3. **Run the executable**:
    - After the compilation, the executable `(ManyCamFlux.exe)` will be located in the `dist` directory. You can run it directly from there.
    - Only the `.exe` file is necessary for the standalone version. It can be portable and moved to another machine if needed.

If PyInstaller is not recognized after installation, try this command:
```sh
python -m PyInstaller --onefile -w -i .\assets\icon.ico .\ManyCamFlux.py
```

*Further updates and adjustments will follow.*
