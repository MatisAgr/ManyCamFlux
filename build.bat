@echo off
rem Windows release build: both versions in .proj\release\ (overwritten if they exist)
rem   ManyCamFlux_<version>_windows.zip   one-folder build (fast start), zipped with its ManyCamFlux\ folder
rem   ManyCamFlux_<version>_portable.exe  single file (unpacks itself on every launch)
rem PyQt5 bundles an old Visual C++ runtime (14.26) that onnxruntime (vision models) cannot load with:
rem it is replaced by this PC's newer one. onnxruntime's optional tools would drag in torch and PyQt6.
setlocal
cd /d "%~dp0"
for /f %%v in ('python -c "from utils import VERSION; print(VERSION)"') do set VERSION=%%v
if "%VERSION%"=="" (echo Cannot read utils.VERSION & exit /b 1)
set OUT=.proj\release
set NAME=ManyCamFlux_%VERSION%
set OPTS=-y -w -i assets\icon.ico --add-data "assets;assets" --add-data "LICENSE;."
for %%f in (MSVCP140 MSVCP140_1 VCRUNTIME140 VCRUNTIME140_1) do call set OPTS=%%OPTS%% "--add-binary=%SystemRoot%\System32\%%f.dll;PyQt5\Qt5\bin"
set OPTS=%OPTS% --exclude-module PyQt6 --exclude-module torch --exclude-module onnxruntime.transformers
set OPTS=%OPTS% --exclude-module onnxruntime.tools --exclude-module onnxruntime.quantization
if not exist %OUT% mkdir %OUT%

echo [1/2] %NAME%_windows.zip
python -m PyInstaller %OPTS% -D ManyCamFlux.py || exit /b 1
copy /y LICENSE dist\ManyCamFlux\ >nul
if exist %OUT%\%NAME%_windows.zip del %OUT%\%NAME%_windows.zip
"%SystemRoot%\System32\tar.exe" -a -c -f %OUT%\%NAME%_windows.zip -C dist ManyCamFlux || exit /b 1

echo [2/2] %NAME%_portable.exe
python -m PyInstaller %OPTS% -F ManyCamFlux.py || exit /b 1
copy /y dist\ManyCamFlux.exe %OUT%\%NAME%_portable.exe >nul || exit /b 1

echo Done: %OUT%\%NAME%_windows.zip and %OUT%\%NAME%_portable.exe
