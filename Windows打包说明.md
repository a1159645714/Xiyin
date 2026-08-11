# Windows 打包

在 Windows 电脑上安装 Python 3.11 或更高版本，以及 Google Chrome。

双击 `build_windows.bat`。打包完成后，程序位于：

```text
dist\XiYinAutoUploader\XiYinAutoUploader.exe
```

脚本还会生成并自动上传以下腾讯云 COS 热更新文件：

```text
release\XiYinAutoUploader_v1.0.6.zip
release\update.json
```

首次使用前，在 Windows 用户环境变量中配置腾讯云密钥：

```bat
setx TENCENTCLOUD_SECRET_ID "你的 SecretId"
setx TENCENTCLOUD_SECRET_KEY "你的 SecretKey"
```

设置后需要关闭并重新打开命令行窗口。建议使用仅有该 COS 存储桶 `updates/` 路径读写权限的子账号密钥，不要使用主账号密钥。

双击脚本后会先上传 ZIP、验证公开访问和文件大小，再最后上传 `update.json`。发布新版本前必须先修改 `config.py` 中的 `APP_VERSION`；脚本会拒绝发布与线上相同或更低的版本。

上传器会优先使用支持断点续传的分片上传；如果子账号没有查询分片任务的存储桶级权限，会自动改用只需要 `PutObject` 权限的单次对象上传。

只需要本地打包、不上传 COS 时，可以执行：

```bat
build_windows.bat --no-upload
```

如果打包成功但上传失败，可以修复网络或密钥配置后单独执行：

```bat
py -3 upload_release.py --release release
```

将整个 `XiYinAutoUploader` 文件夹复制到目标电脑，不要只复制 EXE。

`XiYinUpdater.exe` 必须和主程序放在同一目录。主程序启动后会后台检查 COS 更新清单，用户确认后下载并校验 SHA-256，随后关闭主程序、替换程序文件并自动重启。

首次启动会在 EXE 同目录创建以下可写文件：

```text
app_settings.json
category_catalog.json
cookies.json
playwright_chrome_profile\
```

热更新会保留上述用户数据，以及 `category_catalog_home.json`、`config_profiles\` 和 `output\`。

## 强制停用与升级

发布清单支持以下控制字段：

```json
{
  "minimum_supported_version": "1.0.7",
  "disabled_versions": [],
  "force_update": true,
  "message": "当前版本已停止服务，请升级后继续使用"
}
```

- `minimum_supported_version`：低于该版本的客户端必须升级。
- `disabled_versions`：精确停用指定版本。
- `force_update`：发现更高版本时不允许跳过更新。
- `message`：强制升级或停用时显示给用户的说明。

`build_windows.bat` 默认把当前发布版本设为最低支持版本，并启用强制更新。客户端每次启动都必须在线确认版本状态；无法连接更新服务器时不会进入主界面。客户端也会缓存最近一次有效策略，已经收到的停用指令不会因临时断网而失效。若需要临时放宽策略，可以在上传前编辑 `release\update.json`，再单独运行上传命令。

如需默认登录 Cookie，可将 `cookies.json` 放到 EXE 同目录；也可以启动后在界面中选择 Cookie 文件。
