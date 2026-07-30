# 机械臂串口通信协议

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

## 回复

### `0x80` OK

Payload 第一个字节为被确认数据包的 `SEQ`。

### `0x81` 请求重发

Payload 第一个字节为需要重发数据包的 `SEQ`。

树莓派等待回复 120ms，失败后最多重发 3 次。重发时保持原 SEQ，
并设置 FLAGS.bit4。
