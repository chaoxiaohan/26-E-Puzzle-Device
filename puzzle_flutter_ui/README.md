# 拼图装置 Flutter 控制台

这是与视觉算法分离的横屏 Flutter Linux 前端，目标分辨率为
1024×600，同时可以自适应 1920×1080 显示器。

- 左侧：9:16 竖向实时摄像头画面
- 右侧：第一问、普通拼图、扑克牌三个模式
- 中部：由原始碎片纹理重建的拼接实图
- 底部：碎片数、置信度、耗时、拍照、调参和求解

鲁班猫的安装、运行和验证限制见上级目录的 `README-LUBANCAT.md`。当前版本通过启动脚本的 `PUZZLE_BACKEND_DIR` 连接同级 `puzzle_card_detector` 后端：

- 实时显示摄像头检测画面和二值图；
- 三种模式可分别发起普通或扑克牌求解；
- 显示真实碎片纹理重建结果；
- 阈值、OTSU、目标极性、最小面积均实时生效；
- 拍照保存原图、ROI、二值图和碎片数据；
- 碎片数、置信度、耗时均来自后端状态。

前后端通过 `/tmp/puzzle_ui_*.json/jpg` 内存文件通信，不占用网络端口。
`start_ui.sh` 会在需要时自动启动无窗口视觉后端。

## 构建

```bash
/home/pi5/flutter/bin/flutter analyze
/home/pi5/flutter/bin/flutter test
/home/pi5/flutter/bin/flutter build linux --release
```

## 运行

```bash
./start_ui.sh
```
