@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "SKIP_UPLOAD=0"
if /i "%~1"=="--no-upload" set "SKIP_UPLOAD=1"

if "%SKIP_UPLOAD%"=="0" if not defined TENCENTCLOUD_SECRET_ID goto :missing_credentials
if "%SKIP_UPLOAD%"=="0" if not defined TENCENTCLOUD_SECRET_KEY goto :missing_credentials

py -3 -m pip install --upgrade pip
if errorlevel 1 goto :error
py -3 -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto :error

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "release" rmdir /s /q "release"

py -3 -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name "XiYinAutoUploader" ^
  --distpath "dist" ^
  --workpath "build\main" ^
  --specpath "build\specs" ^
  --add-data "%CD%\category_catalog.json;." ^
  --add-data "%CD%\category_catalog_home.json;." ^
  --add-data "%CD%\combo_arrow.svg;." ^
  --collect-all playwright ^
  --collect-all PIL ^
  main.py
if errorlevel 1 goto :error

py -3 -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onefile ^
  --name "XiYinUpdater" ^
  --distpath "dist\XiYinAutoUploader" ^
  --workpath "build\updater" ^
  --specpath "build\specs" ^
  updater_main.py
if errorlevel 1 goto :error

py -3 build_release.py ^
  --dist "dist\XiYinAutoUploader" ^
  --output "release"
if errorlevel 1 goto :error

if "%SKIP_UPLOAD%"=="0" (
  py -3 upload_release.py --release "release"
  if errorlevel 1 goto :upload_error
)

echo.
echo Build complete: dist\XiYinAutoUploader\XiYinAutoUploader.exe
if "%SKIP_UPLOAD%"=="0" echo COS release files are in the release folder and have been uploaded.
if "%SKIP_UPLOAD%"=="1" echo COS upload was skipped. Release files are in the release folder.
pause
exit /b 0

:missing_credentials
echo.
echo Tencent COS credentials are not configured.
echo Set TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY, then reopen this script.
echo For a local-only build, run: build_windows.bat --no-upload
pause
exit /b 1

:upload_error
echo.
echo Build succeeded, but COS upload failed.
echo Configure TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY, then run:
echo py -3 upload_release.py --release release
pause
exit /b 1

:error
echo.
echo Build failed. Review the error output above.
pause
exit /b 1
