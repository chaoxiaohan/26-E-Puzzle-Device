# 26 电赛 E 题：鲁班猫 1 拼图装置

本分支保存鲁班猫 1 当前已部署、已验证的完整源码、必要资源和本次设备配置快照。原程序由 Python、C++ 与 Flutter Linux 组成。

## 分支

- [raspberry-pi5](https://github.com/chaoxiaohan/26-E-Puzzle-Device/tree/raspberry-pi5)：树莓派 5 当前版本和现场参数。
- [lubancat-1](https://github.com/chaoxiaohan/26-E-Puzzle-Device/tree/lubancat-1)：本分支，鲁班猫 1 适配和求解优化。
- `main`：原有树莓派发布版本保留。

鲁班猫分支使用 `puzzle_card_detector/`、`puzzle_flutter_ui/`，与设备安装目录一致；树莓派分支使用原仓库的 `backend/`、`flutter_ui/`。运行目录分别是树莓派的 `~/puzzle_card_detector`、`~/puzzle_flutter_ui`，以及鲁班猫的 `~/puzzle-device/`。

## 已完成的适配

- Ubuntu 20.04.6 / aarch64 / glibc 2.31，独立 Python 3.13.5 环境。
- 固定 NumPy、OpenCV 和 pyserial 依赖；本机 C++ 求解库与 GTK 启动程序重新编译。
- 自动发现 UVC 摄像头，CH340 固定设备名 `/dev/puzzle-arm`。
- 中文界面默认使用 Flutter 软件渲染，适配原桌面的黑屏问题。
- 配置、模板、ROI 与六点标定数据保留，避免重复启动，并支持后端自动恢复。
- C++ 扫描行/64 位掩码和几何缓存优化：固定用例从 9.86 秒降到约 3.37 秒。

## 源码与构建产物

Git 保存当前设备的 88 个源码、资源、配置与说明文件，原始文件哈希见 `SOURCE-SNAPSHOT.json`。文本文件提交时只统一换行格式。虚拟环境、Python 运行时、Flutter SDK、生成的头文件/引擎、编译产物、wheelhouse 和历史 `captures/` 不纳入 Git。

因此，刚从 Git 克隆的源码还需要生成 Flutter 发布 bundle 和 SDK 头文件；已有的完整离线发布包包含这些产物，可以直接按照 [迁移说明](README-LUBANCAT.md) 恢复。

```bash
git clone --branch lubancat-1 https://github.com/chaoxiaohan/26-E-Puzzle-Device.git puzzle-device
```

已验证的界面构建使用树莓派上的 Flutter 3.44.8 / Dart 3.12.2 SDK，在独立构建目录运行：

```bash
cd puzzle-device/puzzle_flutter_ui
/home/pi5/flutter/bin/flutter build linux --release
tar -czf ../flutter-linux-artifacts.tar.gz build/linux/arm64/release/bundle linux/flutter/ephemeral
```

将该压缩包传到鲁班猫源码的 `puzzle_flutter_ui/` 目录并在那里解压，然后从源码根目录运行 `bash setup_lubancat.sh`。安装脚本会在鲁班猫重新编译 GTK 启动程序以适配 glibc 2.31；不要直接使用树莓派生成的启动程序。系统 apt、Python 与 uv 的首次安装需要可用网络或预先准备好的离线依赖。

```bash
cd puzzle-device/puzzle_flutter_ui
tar -xzf flutter-linux-artifacts.tar.gz
cd ..
bash setup_lubancat.sh
bash puzzle_flutter_ui/start_ui.sh
```

源码快照包含本次设备标定和模板。更新已有设备前保存其配置；摄像头安装位置变化后重新验证 ROI 和六点标定。

## 验证范围

已启用求解期间暂停实时视觉处理，完成或停止后恢复；实时处理采用单线程和 10 FPS 上限。绿色背景实机已验证画面冻结、计时及串口继续、停止后恢复；十种主循环回归场景通过。记录见 [暂停视觉与负载验证](docs/VISION_PAUSE_20261013.md)。

2026-10-13 扑克牌模式已加入跨片切口接合、近矩形半转与完整反向字形串检查，仅测试绿底原图：31/31 张扑克的片序与朝向正确，四矩形样例 4/4；18 张达到自动执行准入。鲁班猫求解中位数 7.73 秒，最长 69.52 秒，复杂样例仍较慢。新版已部署，原有参数保留；摄像头和串口离线，未验证机械臂动作。见 [本轮验证与备份记录](docs/CARD_CUT_TEXT_VALIDATION_20261013.md)。

Python 回归 22/24 通过；两项失败在原树莓派上也存在。Flutter 3 项测试通过。12 组新旧 C++ 求解输出完全一致，2909 组栅格参考与未定义行为检查通过。摄像头和串口仍未连接，实际采集、机械运动和整套执行耗时待联调。

- [迁移、安装和硬件说明](README-LUBANCAT.md)
- [求解优化与实测记录](OPTIMIZATION-20261012.md)

现场源码原版本标识：`fb130304d64e9bb15da61c6965a8b63956676122`。此标识属于本次迁移工作的本地源码历史，当前 GitHub 分支以自身提交记录为准。
