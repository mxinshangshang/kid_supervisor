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

### 2.1 帧数据传输格式 (v4.0)

使用 JPEG 编码传输，替代 v3 的 pickle numpy 数组。

**协议格式**：
```
[4B frame_id][8B timestamp][4B jpeg_len][jpeg_bytes]
```

**发送端 (camera_server.py)**：
```python
_, jpeg_data = cv2.imencode('.jpg', bgr_frame,
                            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
header = struct.pack('!IdI', frame_id, timestamp, len(jpeg_data.tobytes()))
conn.sendall(header)
conn.sendall(jpeg_data.tobytes())
```

**接收端 (inference_client.py)**：
```python
header = recv_exact(conn, 16)  # frame_id(4B) + timestamp(8B) + jpeg_len(4B)
frame_id, timestamp, jpeg_len = struct.unpack('!IdI', header)
jpeg_bytes = recv_exact(conn, jpeg_len)
bgr_frame = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
```

**相比 pickle 的优势**：
- 帧大小从 ~900KB 降至 ~30-50KB（约 20 倍压缩）
- CPU 占用显著降低
- 内存复制减少
- 消除 pickle 反序列化安全风险

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

### 5.2 EMA 平滑滤波

原始距离读数波动较大，使用指数移动平均（EMA）进行平滑：

```
smoothed = α × raw + (1 - α) × last_smoothed
```

配置参数（在 `config.yaml` 中）：
- `smoothing_alpha`: 0.3（默认值，越大越跟随实时值，越小越平滑）
- `min_cm`: 30.0（有效范围下限）
- `max_cm`: 150.0（有效范围上限）

### 5.3 距离置信度 (v4.0)

Camera Module 3 Wide 广角镜头在画面边缘存在畸变，固定焦距估算在边缘区域误差较大。

v4.0 新增距离置信度（`DistanceConfidence`）：
- **HIGH**：人脸 bbox 中心距画面中心 < `edge_reject_ratio`(40%)
- **MEDIUM**：偏离 40%-60%
- **LOW**：偏离 > 60%，不触发距离提醒

### 5.4 校准方法

如需更精确的距离估算，可进行校准：

1. 让人站在已知距离 `D_known` 处
2. 测量人脸像素宽度 `P_measured`
3. 计算焦距：`f = (P_measured × D_known) / W`
4. 更新 `config.yaml` 中的 `distance.camera_focal_length`

---

## 6. 配置参数 (v4.0)

所有参数统一在 `config.yaml` 中管理，不再散落在代码各处。

### 6.1 监督配置 (supervision)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| too_close_threshold_cm | 30.0 | 过近距离阈值（厘米） |
| too_close_duration_s | 5.0 | 过近持续多久才提醒（秒） |
| bad_posture_duration_s | 8.0 | 不良姿态持续多久才提醒（秒） |
| max_study_duration_min | 45 | 最大学习时长（分钟） |
| rest_duration_min | 10 | 休息时长（分钟） |
| alert_cooldown_s | 45.0 | 提醒冷却时间（秒） |
| posture_window_s | 4.0 | 姿态评分滑动窗口（秒） |
| posture_alert_threshold | 60 | 姿态评分触发阈值（0-100） |

### 6.2 检测器配置 (inference)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| model_complexity | 1 | 模型复杂度（0=轻量, 1=平衡, 2=准确） |
| inference_fps | 10 | 推理目标帧率（低于采集帧率） |
| display_fps | 15 | 预览显示目标帧率 |
| analyze_face | false | Face Mesh（开销大，当前未使用输出） |

### 6.3 距离估算配置 (distance)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| face_real_width_cm | 15.0 | 实际人脸宽度（厘米） |
| camera_focal_length | 800.0 | 摄像头焦距（可校准） |
| smoothing_alpha | 0.3 | EMA 平滑因子 |
| edge_reject_ratio | 0.4 | 边缘区域拒绝比例 |

---

## 7. 性能优化

### 7.1 MediaPipe 优化

1. **model_complexity=1**：平衡精度与速度
2. **static_image_mode=False**：启用跟踪模式，比逐帧检测更快
3. **smooth_landmarks=True**：平滑关键点，减少抖动
4. **Face Mesh 默认关闭**：当前未使用其输出，节省 ~50MB 内存和 CPU
5. **温控降频**：CPU > 75°C 时自动降级 model_complexity 和推理帧率

### 7.2 进程调度 (v4.0)

- 摄像头采集 20FPS，推理 10FPS，显示 15FPS
- 推理/显示频率解耦，显示复用最近一次推理结果
- 帧带 timestamp，推理端丢弃积压旧帧
- 性能日志每 10 秒输出（fps、延迟、丢帧数、CPU 温度）

---

## 8. 错误处理

### 8.1 连接断开处理

摄像头服务器：
- 检测到连接断开 → 返回等待状态
- 接受新连接 → 继续发送帧

推理客户端：
- 检测到连接断开 → 清理并退出

### 8.2 子进程自动重启 (v4.0)

主启动器 (`main.py`) 实现了子进程自动重启：
- 任一子进程异常退出后自动重启
- 退避策略：重启间隔递增（2s → 4s → ...，最大 10s）
- 最大重启次数：3 次（可通过 `config.yaml` 配置）
- 超过最大次数后整体退出
- systemd 层保留 `Restart=always` 作为最后防线

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
