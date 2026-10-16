# 树莓派 5：构建、部署和回滚

正式分支：`raspberry-pi5`；开发分支：`raspberry-pi5-adapt-20261016`。算法基线为鲁班猫已验证的 `6de9e25`，包含相同形状碎片、断口/角标识别、10 月 15 日提速，以及求解期间暂停视觉处理。

**2026-10-16 已在 Raspberry Pi 5 / Debian 13 / Python 3.13.5 / Flutter 3.44.8 原生编译并部署。** 41 张绿底回放通过，31 张扑克主图与参考一致；真实画面、只读位置查询与求解暂停/恢复已验证。机械臂实际抓取放置尚未测试。详见 [板端记录](docs/pi5-board-validation-20261016.json)。

## 运行环境

- 树莓派 5，64 位 Raspberry Pi OS / Debian 系 Linux，普通桌面用户运行安装命令。
- Python 3.10–3.13；独立虚拟环境固定 NumPy 2.2.4、OpenCV 4.10.0.84、pyserial 3.5。
- Pi 本机 Flutter Linux SDK。原现场使用 Flutter 3.44.8 / Dart 3.12.2，项目要求 Dart `^3.12.2`。
- 延续原设备的 USB/UVC 摄像头和 CH340 串口；自动选择 UVC 采集节点，跳过 ISP、编码器和 CSI 节点。
- 继承登录桌面的 Wayland/X11 环境，不默认强制鲁班猫的软件渲染选项。

## 上板后的步骤

以下命令在树莓派终端执行，不在 Windows 或鲁班猫上执行。安装时会通过 `sudo` 安装系统依赖，首次构建需要 apt、PyPI 和 Flutter 依赖网络；不要对整个安装脚本使用 sudo。

```bash
git clone --branch raspberry-pi5 https://github.com/chaoxiaohan/26-E-Puzzle-Device.git puzzle-pi5-source
cd puzzle-pi5-source
bash deploy_pi5.sh --check
bash deploy_pi5.sh --prepare-only
```

`--check` 只检查环境。`--prepare-only` 在 `~/.local/share/puzzle-device/releases/` 创建独立发布目录，安装 Python 依赖并在 Pi 上重新编译 C++ 和完整 Flutter bundle；不更改现有程序的启动路径。记下输出的 `PREPARED=` 路径。

关闭旧拼图程序后切换；若仍有旧 UI/后端运行，脚本会拒绝切换：

```bash
bash deploy_pi5.sh --activate /home/pi5/.local/share/puzzle-device/releases/实际发布目录
bash "$HOME/puzzle_flutter_ui/start_ui.sh"
```

`bash deploy_pi5.sh` 可以一次完成构建与切换。SDK 在其他位置时传 `--flutter-bin /实际路径/flutter`；依赖已装好可加 `--skip-apt`；已有适配当前 Python/ARM64 的 wheelhouse 时可加 `--wheelhouse /目录`。更换构建用 Python 可设置 `PUZZLE_SETUP_PYTHON=/usr/bin/python3.13`。

## 数据和回滚

- Git 中的默认 JSON 来自 `raspberry-pi5` 分支 `a5369b9` 的 2026-10-12 快照，仅作新装默认值。切换时复制树莓派原 `~/puzzle_card_detector` 下全部现有 JSON，优先保留现场标定、ROI、模板、串口和评分参数。
- 原 `~/puzzle_card_detector`、`~/puzzle_flutter_ui` 整体移入带时间戳的备份目录，包含原 Git 历史及运行文件。随后在原路径建立指向新发布目录的符号链接；旧快捷方式仍可使用原路径。
- 历史 `captures` 保留在原目录备份中，新版通过链接继续使用；回滚后仍保留新增照片。不要手动删除发布目录或备份目录。
- 虚拟环境留在永久发布路径，不在创建后搬迁。已有 CH340 udev 规则保留；缺失时才安装规则。新增用户组权限需要重新登录，USB 别名需要重新插拔设备后生效。
- 原程序不会被安装脚本自动启动，也不会发送机械臂动作。实际串口、摄像头和标定仍需上板核对。

需要回滚时先关闭 UI/后端，再使用安装输出的 `BACKUP=` 路径：

```bash
bash deploy_pi5.sh --rollback /home/pi5/.local/share/puzzle-device/backups/实际备份目录
```

回滚恢复旧程序及旧配置；新版发布目录仍保留，可找回之后修改的配置。切换失败会尝试恢复原来的两个目录。

## 本地验证

Linux 文件系统部署、连续升级/回滚、失败恢复、配置/照片保留、虚拟环境链接和启动器测试使用模拟程序；它们不代表 GTK/ARM64 或硬件已验证。

```bash
python3 tools/test_pi5_deploy.py
python3 tools/test_pi5_startup.py
cd puzzle_card_detector
python3 -m tests.camera_device_self_test
```

识别回归只使用绿色背景实拍图。本地测试见 `docs/pi5-local-adaptation-20261016.json`，板端测试见 `docs/pi5-board-validation-20261016.json`。

原树莓派快照保留在 `backup/pi5-before-adapt-20261016`，升级前完整压缩备份位于板端 `~/.local/share/puzzle-device/upgrade-20261016/original-programs.tar.gz`，并已下载本地校验。原目录备份位于 `~/.local/share/puzzle-device/backups/20261016-211831-bf4e15a1/`。

切换时五份参数均原样保留；之后用户在界面调整了 ROI 为 `(86,277,549,729)`，该调整已确认并保留。回滚会恢复升级前的旧配置，新配置仍在新版发布目录中。
