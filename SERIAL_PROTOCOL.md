# 拼图平台串口通信协议

## 串口参数

- 115200 波特率
- 8 数据位、1 停止位、无校验、无流控
- 多字节整数采用小端序

## 数据帧

```text
AA 55 | CMD | FLAGS | SEQ | LEN | PAYLOAD | CRC16_L | CRC16_H
```

- 不使用包尾。
- CRC 使用 CRC16-CCITT-FALSE。
- 多项式 `0x1021`，初始值 `0xFFFF`。
- CRC 范围为 `CMD` 到 `PAYLOAD` 末尾，不包含 `AA 55`。

FLAGS：

- bit0：相对旋转或相对移动
- bit4：重发包
- bit5：要求回复
- 其余位保留

## 命令

### `0x10` 完整抓取动作

Payload 格式：

```c
uint8_t task_id;
uint8_t action_index;
uint8_t action_count;
uint8_t piece_id;
int32_t pick_x;
int32_t pick_y;
int32_t pick_z;
int32_t place_x;
int32_t place_y;
int32_t place_z;
int16_t rotation_cdeg;
```

`rotation_cdeg` 的单位为 `0.01°`，正数表示逆时针。

### `0x11` 开始执行

Payload：

```c
uint8_t task_id;
```

树莓派收到所有动作的 OK 后才发送该命令。

### `0x20` 手动控制

Payload：

```c
uint8_t control_type;
int32_t x;
int32_t y;
int32_t z;
int16_t rotation_cdeg;
```

control_type：

- `1`：绝对移动
- `2`：相对移动
- `3`：归零，后续数据填 0
- `4`：查询平台当前位置，后续数据填 0

## 回复

### `0x80` OK

普通命令的 Payload 第一个字节为被确认数据包的 `SEQ`。

查询当前位置时，OK Payload 为：

```c
uint8_t seq;
int32_t current_x;
int32_t current_y;
int32_t current_z;
int16_t current_rotation_cdeg;
```

### `0x81` 请求重发

Payload 第一个字节为需要重发数据包的 `SEQ`。

树莓派等待回复 120ms，失败后最多重发 3 次。重发时保持原 SEQ，
并设置 FLAGS.bit4。

## 三点仿射坐标标定

树莓派记录：

- A点：A4纸右上角的视觉像素坐标和平台坐标
- B点：A4纸左下角的视觉像素坐标和平台坐标
- C点：A4纸左上角的视觉像素坐标和平台坐标

三个点必须不共线。树莓派根据三组对应坐标计算二维仿射矩阵：

```text
[platform_x]   [a b c] [visual_x]
[platform_y] = [d e f] [visual_y]
                        [   1    ]
```

它可以同时补偿平移、旋转、X/Y 比例差异和轻微斜切。三个点近似
共线时会拒绝保存，避免产生不稳定的坐标换算结果。

自动抓取动作只有在标定完成后才允许发送。
