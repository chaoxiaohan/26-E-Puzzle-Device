# 拼图装置 Flutter 控制台

这是与视觉算法分离的横屏 Flutter Linux 前端，目标分辨率为
1024×600，同时可以自适应 1920×1080 显示器。

- 左侧：9:16 竖向实时摄像头画面
- 右侧：第一问、普通拼图、扑克牌三个模式
- 中部：由原始碎片纹理重建的拼接实图
- 底部：碎片数、置信度、耗时、拍照、调参和求解

当前版本是可交互的界面原型，使用真实抓拍重建图作为结果区示例。
后续由 Python 视觉后端提供实时帧、状态和实际求解结果。

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
