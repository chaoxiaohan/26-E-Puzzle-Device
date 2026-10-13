# 鲁班猫 1 拼图装置迁移

迁移日期：2026-10-12。目标：EmbedFire LubanCat-1，Ubuntu 20.04.6，aarch64，glibc 2.31。

程序安装在 `/home/cat/puzzle-device`。桌面应用菜单中的“拼图装置”可启动界面，登录桌面时也会自动启动。

2026-10-13 已部署 `cut-text-integrity-20261013`：补充切口图案接合、近矩形半转和两端完整字形串检查，修复方块 7 与大小王两例。鲁班猫仅回放绿底原图，31/31 张扑克牌的片序与朝向正确，四矩形样例 4/4；18 张达到自动执行准入，另外 13 张保留确认提示。板端求解中位数 7.73 秒，最长 69.52 秒，复杂样例仍较慢；摄像头及机械臂动作未实测。范围、逐例结果与备份见 [本轮验证记录](docs/CARD_CUT_TEXT_VALIDATION_20261013.md)。

```bash
bash /home/cat/puzzle-device/puzzle_flutter_ui/start_ui.sh
```

## 程序结构

| 目录或文件 | 用途 |
| --- | --- |
| `puzzle_card_detector/main.py` | 视觉处理、求解调度、运动规划和主循环 |
| `maix.py`、`hardware_devices.py` | OpenCV 对原 MaixPy 接口的兼容及 USB 摄像头发现 |
| `puzzle_solver.py`、`solver_*.py`、`layout_constraints.py` | 几何拼图、约束检查和修复 |
| `card_face_solver.py`、`card_topology_solver.py` | 扑克牌纹理、角标和拓扑求解 |
| `rectangle_solver.cpp`、`cpp_rectangle_solver.py` | 本机 C++ 加速求解及 Python 接口 |
| `serial_protocol.py` | USB 串口、平台控制和六点仿射标定 |
| `ui_bridge.py` | `/tmp/puzzle_ui_*` JSON 状态、命令和 JPEG 图片通信 |
| `captures/`、`templates.json`、各类 `*_settings.json` | 历史采集、学习模板、参数与标定数据 |
| `puzzle_flutter_ui/lib/main.dart`、`backend_bridge.dart` | Flutter 中文界面与后端通信 |
| `setup_lubancat.sh` | 依赖、独立 Python、本机编译、udev 和桌面启动安装 |

原始程序来自树莓派正在运行的 `/home/pi5/puzzle_card_detector` 和 `/home/pi5/puzzle_flutter_ui`。原始快照有 463 个文件，其中 288 个在 captures 下，包含当前未提交的视觉参数。原程序目录及运行程序未被覆盖；Flutter 在树莓派独立的构建副本中编译。

## 适配说明

- 系统 Python 保留；程序使用 `.python/` 下的 Python 3.13.5 和后端 `.venv/`。
- 依赖固定为 NumPy 2.2.4、OpenCV 4.10.0.84、pyserial 3.5；`wheelhouse/` 提供 ARM64 离线安装包。
- 去除运行时固定的树莓派路径；历史图片输出到后端自身的 `captures/`。
- C++ 求解库在鲁班猫重新编译。Flutter 的 Dart 发布包在树莓派独立副本编译，GTK 启动程序在鲁班猫编译以兼容 glibc 2.31。
- Ubuntu 20.04 的 Flutter OpenGL 路径曾黑屏；启动脚本默认 `FLUTTER_LINUX_RENDERER=software`。当前中文界面、文件图片显示和页面切换已验证。Flutter 提示此渲染器为实验功能；实时摄像头帧率待实机测量。
- 摄像头默认 `PUZZLE_CAMERA=auto`，选择 UVC 驱动且 index=0 的视频节点，排除 Rockchip 编解码节点。多摄像头时可显式指定节点。
- CH340 使用 `/dev/puzzle-arm`，保留 115200 波特率和原六点标定数值；安装 udev 规则，并将用户加入 dialout、video、render 组。
- 启动锁防止界面和后端重复运行。后端自动重启只匹配本程序路径。
- 安装 fake-hwclock 保存并恢复关机前时间，原 NTP 服务保留。此功能不是电池 RTC，也不能补算关机时长或保证联网对时成功。

## 安装或恢复

适配发布包包含完整程序、Flutter 发布产物、独立 Python、uv 和 Python wheelhouse。解压后运行：

```bash
tar -xzf puzzle-lubancat-optimized-20261012.tar.gz -C /home/cat
bash /home/cat/puzzle-device/setup_lubancat.sh
```

不要直接覆盖一个已有且存放了新标定数据的目录；先备份已有目录。安装脚本支持在同一目录重复执行。完整包的 Python 安装不需要联网，系统 apt 依赖在缺少时仍需可用的软件源。`sudo` 需有权限；新用户的组权限在下次登录后生效。

完整包含构建 Flutter 所需的当前 SDK 头文件与发布引擎。重新编译 GTK 启动程序和 C++ 库：

```bash
bash /home/cat/puzzle-device/puzzle_card_detector/build_cpp_solver.sh
bash /home/cat/puzzle-device/puzzle_flutter_ui/build_lubancat_runner.sh
```

修改 Dart 界面后，需要 ARM64 Flutter 3.44.8 SDK，先在界面目录运行 `flutter build linux --release`，再在鲁班猫运行 `build_lubancat_runner.sh`。完整 SDK 不打进迁移包。

## 硬件接入与检查

```bash
v4l2-ctl --list-devices
ls -l /dev/puzzle-arm
id
tail -n 30 /tmp/puzzle_backend.log
```

未接硬件时，界面显示摄像头离线和串口自动重连，相关运动按钮不可用。接入后程序会自动重试。明确选择摄像头的例子：

```bash
PUZZLE_CAMERA=/dev/video2 bash /home/cat/puzzle-device/puzzle_flutter_ui/start_ui.sh
```

修改启动环境前先退出已有界面和后端，避免现有进程仍使用原环境。迁移保存了树莓派上的原标定数据；摄像头安装位置或平台坐标变化后，应重新完成界面的六点标定再执行运动。

## 验证记录和限制

优化后 Python 3.13.5 回归 24 项中通过 22 项，Flutter widget 测试 3 项通过。摄像头发现和断线恢复、串口协议模拟、桥接和多类求解回归通过。中文拼图页、平台页、设置页和模式切换已在鲁班猫桌面检查。

未通过的两项保留原断言：

1. `card_face_solver_self_test`：同侧角标合成样本的置信度为 0，原断言要求至少 0.55；原树莓派也失败。
2. `self_test`：低分候选仍被返回，原断言要求拒绝；原树莓派也失败。当前代码存在 BEST 保底候选策略，不能仅依据旧测试直接修改运动或求解行为。

`best_effort_self_test` 的 6 秒限制已通过。相同固定用例在优化前需 9.86 秒，优化后三次实测为 3.425、3.373、3.368 秒，中位数 3.373 秒，耗时减少 65.8%。这些测量保持中文界面和后端运行，但摄像头、串口未连接；其他输入及硬件接入后的耗时需分别测量。

C++ 优化包括扫描行填充、64 位批量 3x3 内部掩码计算、候选边长度预计算，以及重叠/距离缓存；搜索比例、填充率、步长、480 状态束宽、评分、重叠限制和两线程均保持原值。12 组新旧库对比的布局、评分、节点数和元数据完全一致。2909 组栅格与逐像素参考实现完全一致，未定义行为检查通过。详细记录见 `OPTIMIZATION-20261012.md`。

未连接真实摄像头和串口：USB 实际采集、断插恢复、实际运动、拼装精度、连续运行以及实时帧率均未完成硬件验收。fake-hwclock 的文件保存和服务启用可检查，完整重启恢复仍需实际重启验证。
