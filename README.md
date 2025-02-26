# ManyCamFlux

ManyCamFlux is a tiny project designed to manage multiple webcam feeds using a single Python file. It provides a simple interface to view, control, and capture screenshots from multiple cameras simultaneously.

## Features

- **Single File Implementation**: The entire project is contained within a single Python file (`ManyCamFlux.py`).
- **Multiple Camera Support**: Automatically detects and displays feeds from multiple cameras.
- **Camera Controls**: Adjust brightness, contrast, and rotation for each camera feed.
- **Screenshot Capture**: Capture screenshots at regular intervals and save them to a specified folder.
- **Configuration Management**: Save and load camera settings and configurations.

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

## Build with PyInstaller

To build your modifications of ManyCamFlux project into a standalone executable using PyInstaller, follow these steps:

1. **Install PyInstaller**:
    ```sh
    pip install pyinstaller
    ```

2. **Compile the project**:
    ```sh
    pyinstaller --onefile --windowed ManyCamFlux.py
    ```

3. **Run the executable**:
    - After the compilation, the executable `(ManyCamFlux.exe)` will be located in the `dist` directory. You can run it directly from there.
    - Only the `.exe` file is necessary for the standalone version. It can be portable and moved to another machine if needed.

If PyInstaller is not recognized after installation, try this command:
```sh
python -m PyInstaller --onefile --windowed ManyCamFlux.py
```