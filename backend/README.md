# 树莓派5拼图程序

这是 MaixCAM2 拼图程序的树莓派5兼容版。

- `main.py`：原识别、自动拼图、旋转规划算法。
- `maix.py`：用 OpenCV 模拟原 MaixPy 相机、显示、绘图和触摸接口。
- `start.sh`：在树莓派桌面上启动程序。

## 硬件

- 树莓派5
- USB摄像头：`/dev/video0`
- 摄像头模式：MJPG、1280×720、30 FPS

## 启动

```bash
cd /home/pi5/puzzle_card_detector
./start.sh
```

按键可用鼠标点击，也可以使用映射为鼠标左键的触摸屏。按键盘 `Q` 或
`Esc` 退出。

程序默认使用720×1280竖屏画布。摄像头仍以1280×720采集，然后截取中间
720×720区域放在竖屏上方；ROI、文字、按钮和触摸全部直接使用竖屏坐标，
最终画面不再旋转。可通过`start.sh`中的`PUZZLE_PORTRAIT_CROP_X`调整横向
裁剪起点，默认值280对应原图中间区域。

## SSH无窗口测试

```bash
cd /home/pi5/puzzle_detector
PUZZLE_HEADLESS=1 PUZZLE_MAX_FRAMES=30 python3 main.py
```

摄像头不是 `/dev/video0` 时：

```bash
PUZZLE_CAMERA=/dev/video2 ./start.sh
```

只检查拼图算法：

```bash
python3 self_test.py
```

## Flutter 控制台

Flutter 控制台运行时使用无窗口后端：

```bash
PUZZLE_HEADLESS=1 ./start.sh
```

`ui_bridge.py` 负责输出实时画面、二值图、拼接实图和 JSON 状态，并
接收模式、求解、拍照及调参命令。通信文件位于 `/tmp/puzzle_ui_*`，
摄像头和求解算法仍全部由本程序管理。

## 稳定识别与快速求解

- 黑纸拼片默认锁定为 `DARK`，不再自动切换亮暗极性。
- 只保留题目允许的3～5边轮廓。
- 点击 `SOLVE` 时使用最近3秒内面积最完整的4块轮廓。
- `SOLVE OK` 表示通过严格覆盖检查。
- 只有通过覆盖率与重叠率检查时才显示拼接结果，低分候选不会强制输出。
- 目标布局不增加像素外移，直接使用原始闭合位置。
