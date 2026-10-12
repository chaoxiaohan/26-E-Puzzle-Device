# 26 电赛 E 题：拼图装置

树莓派 5 上运行的拼图装置工程，包含视觉后端、Flutter 控制台、平台串口通信与坐标标定。

## 功能

- 第一问模板学习与普通几何拼图；
- 白底扑克牌碎片拼图；
- USB 摄像头实时识别、ROI 与阈值调参；
- 碎片抓取、旋转、放置动作规划；
- 串口平台控制与六点仿射标定；
- Flutter 横屏控制界面。

## 目录

- `backend/`：OpenCV 视觉、拼图求解、动作规划、串口协议；
- `flutter_ui/`：Flutter Linux 控制台；
- `docs/`：串口通信协议；
- `deploy_pi5.sh`：树莓派 5 一键部署与启动脚本。

## 硬件与系统环境

- Raspberry Pi 5，64 位 Raspberry Pi OS / Debian；
- USB 摄像头，默认 `/dev/video0`，MJPG、1280×720；
- 1024×600 或更高分辨率横屏；
- 可选：CH340 USB 串口平台控制器；
- Python 3、OpenCV、NumPy、pyserial；
- ARM64 Flutter SDK。默认位置为 `/home/pi5/flutter`。

## 一键部署

在树莓派桌面终端执行：

```bash
git clone https://github.com/chaoxiaohan/26-E-Puzzle-Device.git
cd 26-E-Puzzle-Device
chmod +x deploy_pi5.sh
./deploy_pi5.sh
```

脚本会安装系统依赖，部署后端至 `~/puzzle_card_detector`、部署 Flutter 前端至
`~/puzzle_flutter_ui`，编译 C++ 求解器和 Flutter Linux 程序，并启动控制台。

若 Flutter 不在默认位置：

```bash
FLUTTER_BIN=/opt/flutter/bin/flutter ./deploy_pi5.sh
```

首次部署前需要先准备 ARM64 Flutter SDK。项目已经验证过的默认路径是
`/home/pi5/flutter/bin/flutter`。

## 日常启动

已部署后，直接执行：

```bash
~/puzzle_flutter_ui/start_all.sh
```

前端会在视觉后端未运行时自动启动后端。只启动后端调试：

```bash
cd ~/puzzle_card_detector
./start.sh
```

无显示器测试：

```bash
cd ~/puzzle_card_detector
PUZZLE_HEADLESS=1 python3 main.py
```

## 运行时文件

以下文件是现场设备相关配置，不建议覆盖或提交：

- `vision_settings.json`：ROI、阈值和背景设置；
- `serial_settings.json`：串口设备与波特率；
- `roi_settings.json`、`templates.json`：标定与第一问模板；
- `captures/`：拍照记录；
- `librectangle_solver.so`、`flutter_ui/build/`：编译产物。

`deploy_pi5.sh` 更新代码时会保留这些文件。

## 设备分支和当前快照

- `raspberry-pi5`：树莓派 5 当前源码与现场参数快照，后端原提交 `410ded8`，界面原提交 `2304d77`。
- `lubancat-1`：鲁班猫 1 的 Python 3.13、摄像头发现、中文界面兼容和 C++ 求解优化。
- `main`：原有发布分支保留。

本分支在 2026-10-12 从树莓派当前运行目录逐文件核对。代码及 Flutter 资源与原 `main` 一致；新增保存了现场 `vision_settings.json`、`serial_settings.json`、`roi_settings.json`、`templates.json`，并修正中文 PDF 文件名。完整文件哈希及原设备 Git 状态见 `SOURCE-SNAPSHOT.json`。

这些配置是本次设备快照。原部署脚本会保留目标设备已有配置，并在同步时排除这些文件；新设备需要使用快照配置时，可在部署后端目录后手动复制，再根据实际摄像头位置重新验证 ROI 和六点标定。

```bash
git clone --branch raspberry-pi5 https://github.com/chaoxiaohan/26-E-Puzzle-Device.git
```

Git 保存源码、必要资源和此次配置快照；历史采集图片、虚拟环境、Flutter SDK、wheelhouse 和编译产物未纳入源码分支。
