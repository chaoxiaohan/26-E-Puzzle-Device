# 26电赛E题：拼图装置

本仓库包含树莓派5上的拼图视觉后端、Flutter横屏控制界面，以及平台串口通信协议。

## 项目状态

完赛版本。

当前视觉识别、普通拼图、扑克牌拼图、六点平台标定、动作规划和串口控制流程已经贯通。后续仍可继续提高：

- 拼接边距和末块落点精度。
- 扑克牌花纹对齐与卡牌拼图稳定性。

## 目录

- `backend/`：碎片识别、矩形求解、扑克牌纹理求解、动作规划、串口通信。
- `flutter_ui/`：横屏控制台、视觉调参、平台点动、串口设置和平台标定界面。
- `docs/`：平台串口通信协议。

## 硬件环境

- 树莓派5
- USB摄像头
- 1024×600或更高分辨率横屏
- 串口连接的XYZ旋转平台

## 构建界面

```bash
cd flutter_ui
/home/pi5/flutter/bin/flutter analyze
/home/pi5/flutter/bin/flutter test
/home/pi5/flutter/bin/flutter build linux --release
```

## 启动

部署时保持两个目录位于同一父目录，并按实际路径调整启动脚本中的目录：

```bash
cd flutter_ui
./start_all.sh
```

`start_ui.sh` 会在视觉后端未运行时启动 `backend/main.py`。摄像头暂时离线时，
后端会等待设备恢复，串口设置和平台控制仍可使用。

## 注意

- `backend/serial_settings.json`、拍照数据、运行日志和编译产物不会提交。
- 平台坐标单位由执行端定义，但串口收发必须始终使用同一种单位。
- 自动执行前需要先完成视觉坐标到平台坐标的标定。
