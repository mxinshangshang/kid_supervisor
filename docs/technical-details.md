# 技术实现细节

## 1. 颜色空间处理

### 1.1 颜色空间转换

系统中存在两种颜色空间：

- **RGB888**：Picamera2 采集输出格式
- **BGR**：OpenCV 期望的输入格式

**转换关系**：
```
Picamera2 (RGB) ──┐
                  ├─> MediaPipe (需要 RGB)
OpenCV (BGR)  ────┘
```

**代码中的处理**：
```python
# camera_server.py: Picamera2 直接输出 RGB
preview_config = picam2.create_preview_configuration(
    main={"format": "RGB888", "size": FRAME_SIZE}
)

# inference_client.py: MediaPipe 使用 RGB，OpenCV 渲染时转 BGR
frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
```

---

## 2. 序列化与反序列化

### 2.1 帧数据传输格式

使用 Python `pickle` 序列化 numpy 数组：

```python
# 发送端
data = pickle.dumps(frame)  # numpy array -> bytes
conn.sendall(struct.pack('!I', len(data)))  # 4 字节长度（网络字节序）
conn.sendall(data)

# 接收端
data_len = struct.unpack('!I', conn.recv(4))[0]
data = b''
while len(data) < data_len:
    data += conn.recv(data_len - len(data))
frame = pickle.loads(data)
```

**优点**：
- 实现简单
- numpy 原生支持
- 保留完整 dtype 和 shape 信息

**缺点**：
- 仅 Python 间通信
- pickle 数据不可跨版本兼容（本项目两个进程版本不同，但只传 numpy，安全）

---

## 3. MediaPipe 关键点

### 3.1 Pose 关键点索引

MediaPipe Pose 输出 33 个人体关键点：

| 索引 | 部位 | 用途 |
|------|------|------|
| 0 | 鼻子 (NOSE) | 人脸定位、头部姿态 |
| 7 | 左耳 (LEFT_EAR) | 头部姿态 |
| 8 | 右耳 (RIGHT_EAR) | 头部姿态 |
| 11 | 左肩 (LEFT_SHOULDER) | 姿态分析 |
| 12 | 右肩 (RIGHT_SHOULDER) | 姿态分析 |
| 23 | 左髋 (LEFT_HIP) | 姿态分析 |
| 24 | 右髋 (RIGHT_HIP) | 姿态分析 |

### 3.2 坐标系统

MediaPipe 使用归一化坐标：
- x, y: [0.0, 1.0]，相对于画面宽高
- z: 深度，相对于臀部

转换为像素坐标：
```python
def get_p(landmark, w, h):
    return (landmark.x * w, landmark.y * h)
```

---

## 4. 防抖机制

### 4.1 存在检测防抖

为避免误检导致的频繁启停计时，采用防抖策略：

**检测到人**：
```
计数器从 0 开始累加
→ 连续 2 帧检测成功 → 确认真正存在
```

**人离开**：
```
计数器从 0 开始累加
→ 连续 3 帧未检测到 → 确认离开
```

**代码实现**：
```python
# inference_client.py
if detection_result.success:
    person_gone_counter = 0
    person_counter = min(person_counter + 1, 3)
    if person_counter >= 2 and not person_detected:
        person_detected = True
        supervisor.on_person_detected(current_time)
else:
    person_counter = 0
    person_gone_counter = min(person_gone_counter + 1, 5)
    if person_gone_counter >= 3 and person_detected:
        person_detected = False
        supervisor.on_person_left(current_time)
```

### 4.2 状态提醒防抖

避免频繁提醒用户，采用冷却机制：

```
同一类型提醒
→ 触发后开始冷却计时
→ 冷却期内不再重复提醒
→ 冷却期结束后可再次触发
```

**配置**（默认值）：
```python
alert_cooldown: float = 30.0  # 30 秒
```

---

## 5. 距离估计算法

### 5.1 相似三角形原理

```
       (摄像头)
          ●
         /|\
        / | \
       /  |  \
      /   |f  \
     /    |    \
    /     |     \
   ●──────┴──────● (实际人脸，宽度 W)
          |
          | 距离 D
          |
   ●──────┴──────● (成像人脸，宽度 P)
      (图像平面)
```

**公式推导**：
```
由相似三角形：
P / f = W / D

→ D = (W × f) / P

其中：
W: 实际人脸宽度（约 15 cm）
f: 摄像头焦距（预设 600，可校准）
P: 人脸像素宽度
```

### 5.2 校准方法

如需更精确的距离估算，可进行校准：

1. 让人站在已知距离 `D_known` 处
2. 测量人脸像素宽度 `P_measured`
3. 计算焦距：`f = (P_measured × D_known) / W`
4. 更新代码中的 `camera_focal_length` 参数

---

## 6. 配置参数

### 6.1 监督配置 (SupervisionConfig)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| too_close_threshold_cm | 35.0 | 过近距离阈值（厘米） |
| too_close_duration | 3.0 | 过近持续多久才提醒（秒） |
| bad_posture_duration | 5.0 | 不良姿态持续多久才提醒（秒） |
| max_study_duration | 2700.0 | 最大学习时长（45 分钟，秒） |
| rest_duration | 600.0 | 休息时长（10 分钟，秒） |
| alert_cooldown | 30.0 | 提醒冷却时间（秒） |

### 6.2 检测器配置 (MediaPipePoseDetector)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| model_complexity | 1 | 模型复杂度（0=轻量, 1=平衡, 2=准确） |
| enable_segmentation | False | 是否启用分割 |
| smooth_landmarks | True | 是否平滑关键点 |
| min_detection_confidence | 0.5 | 最小检测置信度 |
| min_tracking_confidence | 0.5 | 最小跟踪置信度 |
| face_real_width_cm | 15.0 | 实际人脸宽度（厘米） |
| camera_focal_length | 600.0 | 摄像头焦距（可校准） |

---

## 7. 性能优化

### 7.1 MediaPipe 优化

1. **model_complexity=1**：平衡精度与速度
2. **static_image_mode=False**：启用跟踪模式，比逐帧检测更快
3. **smooth_landmarks=True**：平滑关键点，减少抖动
4. **Face Mesh 懒加载**：仅在需要时初始化

### 7.2 进程调度

- 摄像头服务器尽可能快地采集
- 推理客户端按自身能力处理，不阻塞采集
- Socket 缓冲区自动处理背压

---

## 8. 错误处理

### 8.1 连接断开处理

摄像头服务器：
- 检测到连接断开 → 返回等待状态
- 接受新连接 → 继续发送帧

推理客户端：
- 检测到连接断开 → 清理并退出
- 依赖主启动器重启（当前未实现自动重启）

### 8.2 异常处理策略

- **MediaPipe 失败**：记录错误，继续尝试下一帧
- **渲染失败**：忽略错误，不影响主流程
- **窗口关闭失败**：try-catch 包裹，不阻止退出

---

## 9. 预留接口

### 9.1 音频模块 (src/audio/)

预留了音频相关模块，待后续实现：

- `wake_word.py`：唤醒词检测（如 Porcupine / openWakeWord）
- `stt.py`：语音转文字（如 Whisper / Vosk）
- `tts.py`：文字转语音（如 Piper / eSpeak）

### 9.2 通知模块 (src/notifier.py)

预留了通知模块接口，用于：
- 语音提醒（TTS）
- 其他通知方式（如推送）

---

*文档版本：v1.0*  
*最后更新：2026-06-01*
