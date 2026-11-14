# 清影 QingYing

Windows 素材工作台：链接下载、水印修复、小红书采集、Facebook 主页与 X 图片采集。

新版采用黑灰玻璃界面、胶囊导航和一体窗口控制，包含银白取景框图标；保留原有业务模块、兼容界面、取消续传和本地历史。

<p align="center"><img src="source/assets/qingying-icon.png" width="180" alt="清影图标"></p>

## 运行

便携版完整解压后运行 `清影.exe`，并保持 `_internal` 与程序位于同一目录。完整运行依赖不放入 Git；仅下载 EXE 不能代替完整便携包。

源码环境：Windows、Python 3.10、系统 Tk、Edge/Chrome 及 WebView2。

```powershell
python -m pip install -r requirements.txt
python source/app.py
# 原生兼容界面
python source/app.py --classic
```

依赖版本取自现有发行包，本次未重新安装依赖验证。登录操作在独立浏览器中完成；平台可用性取决于登录、网络与平台状态。

## 功能

- 多条链接下载、剪贴板、静音、Cookie、Instagram 登录、取消及续传。
- 图片和视频框选水印、撤销、清空、图片预览、修复保存。
- 小红书关键词/话题、模式、排序、翻页、缩略图、勾选保存。
- Facebook 主页照片/相册/视频/Reels 采集、数量设置与暂停。
- X 主页/评论图片、登录、预览与勾选下载。
- 更新检查、本地目录、日志、去重历史与完整原生工具入口。

## 目录和检查

`source` 为源码和图标；`tests` 为离线回归；`tools` 为现有发行包维护工具；`docs` 为界面实现说明。

```powershell
python tests/regression_checks.py
python tests/glass_bridge_checks.py
# 已有完整 Windows 发行包放在 清影/ 时，可用内置 Python：
.\tools\run_bundled_python.ps1 -ScriptPath tests\regression_checks.py
```

`update_bundle.py` 依赖已有发行包，不是从零构建脚本。`package_portable.py` 打包程序、依赖、说明与许可证，并验证归档和逐文件 SHA-256；排除账号、配置、会话、历史与下载任务。

## 数据与许可

仓库不含浏览器会话、Cookie、个人设置、历史数据库、待下载任务和用户素材。运行产生的数据保存在本机。第三方组件与许可见 [第三方组件](第三方组件.md) 和 `第三方许可证`；项目自身尚未声明开源许可证。
