@echo off
setlocal
cd /d "%~dp0"

py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt pyinstaller
py -3 -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name "XiYinAutoUploader" ^
  --add-data "category_catalog.json;." ^
  --add-data "category_catalog_home.json;." ^
  --add-data "combo_arrow.svg;." ^
  --collect-all playwright ^
  --collect-all PIL ^
  main.py
echo.
echo Build complete: dist\XiYinAutoUploader\XiYinAutoUploader.exe
pause
