# Windows 打包

在 Windows 电脑上安装 Python 3.11 或更高版本，以及 Google Chrome。

双击 `build_windows.bat`。打包完成后，程序位于：

```text
dist\XiYinAutoUploader\XiYinAutoUploader.exe
```

将整个 `XiYinAutoUploader` 文件夹复制到目标电脑，不要只复制 EXE。

首次启动会在 EXE 同目录创建以下可写文件：

```text
app_settings.json
category_catalog.json
cookies.json
playwright_chrome_profile\
```

如需默认登录 Cookie，可将 `cookies.json` 放到 EXE 同目录；也可以启动后在界面中选择 Cookie 文件。
