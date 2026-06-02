# 技术实现细节

## 1. 颜色空间处理

### 1.1 颜色空间转换

系统中存在两种颜色空间：

- **RGB888**：Picamera2 采集输出格式
- **BGR**：OpenCV 期望的输入格式

**转换关系 (v4.0 实测修正)**：
```
Picamera2 (RGB) ──┐
                  ├─> MediaPipe (需要 RGB)
                  │
OpenCV JPEG 编解码需要 BGR ──┘

注意：在此树莓派环境下，cv2.imshow() 需要 RGB 才能正常显示颜色！
```

**代码中的处理 (v4.0 最终版)**：
```python
# ==================== camera_server.py ====================
# Picamera2 直接输出 RGB
preview_config = picam2.create_preview_configuration(
    main={"format": "RGB888", "size": FRAME_SIZE}
)

# JPEG 编码前转 BGR (cv2.imencode 需要 BGR)
bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
_, jpeg_data = cv2.imencode('.jpg', bgr_frame, ...)

# ==================== inference_client.py ====================
# JPEG 解码得到 BGR
jpeg_array = np.frombuffer(jpeg_bytes, dtype=np.uint8)
bgr_frame = cv2.imdecode(jpeg_array, cv2.IMREAD_COLOR)

# 转 RGB 给 MediaPipe 推理
rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)

# 预览显示：再转回 RGB (此环境下 cv2.imshow 需要 RGB！)
frame_for_preview = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
```

### 1.2 颜色问题调试记录

| 版本 | 问题 | 解决方案 |
|------|------|---------|
| v3 | 颜色正常 | pickle RAW 直接传递 RGB |
| v4.0 初版 | 肤色偏蓝/偏红 | 原因：cv2.imshow 期望格式与常规不同 |
| v4.0 修正 | 颜色正常 | 预览前再做一次 BGR→RGB 转换 |

---

## 2. 序列化与反序列化

### 2.1 帧数据传输格式 (v4.0)

使用 JPEG 编码传输，替代 v3 的 pickle numpy 数组。

**协议格式**：
```
┌─────────────┬──────────────────┬──────────────┬──────────────────┐
│  4 字节     │    8 字节        │   4 字节     │  变长字节        │
│  frame_id   │   timestamp      │  jpeg_len    │  jpeg_data       │
│ (BigEndian) │  (double)        │ (BigEndian)  │  (JPEG 压缩帧)   │
└─────────────┴──────────────────┴──────────────┴──────────────────┘
```

**协议字段说明**：

| 字段 | 类型 | 字节序 | 说明 |
|------|------|--------|------|
| frame_id | uint32 | Big Endian | 单调递增帧序号，从 0 开始 |
| timestamp | double | - | Unix 时间戳，精确到微秒 |
| jpeg_len | uint32 | Big Endian | JPEG 数据长度 |
| jpeg_data | bytes | - | JPEG 编码的视频帧 |

**发送端 (camera_server.py)**：
```python
def send_frame(conn, frame_id, timestamp, frame):
    try:
        # RGB → BGR for JPEG encoding
        bgr_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        _, jpeg_data = cv2.imencode('.jpg', bgr_frame,
                                    [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        jpeg_bytes = jpeg_data.tobytes()

        # 先发元数据：frame_id(4B) + timestamp(8B) + jpeg_len(4B)
        header = struct.pack('!IdI', frame_id, timestamp, len(jpeg_bytes))
        conn.sendall(header)
        # 再发 JPEG 数据
        conn.sendall(jpeg_bytes)
        return True
    except (BrokenPipeError, ConnectionResetError):
        # 连接断开是正常的，不刷屏
        return False
    except Exception as e:
        print(f"[Camera] 发送失败: {e}")
        return False
```

**接收端 (inference_client.py)**：
```python
def recv_frame(conn):
    try:
        # 接收元数据：frame_id(4B) + timestamp(8B) + jpeg_len(4B)
        header = b""
        while len(header) < 16:
            chunk = conn.recv(16 - len(header))
            if not chunk:
                return None, None, None, None
            header += chunk

        frame_id, timestamp, jpeg_len = struct.unpack('!IdI', header)

        # 接收 JPEG 数据
        data = b""
        while len(data) < jpeg_len:
            packet = conn.recv(jpeg_len - len(data))
            if not packet:
                return None, None, None, None
            data += packet

        # JPEG 解码
        jpeg_array = np.frombuffer(data, dtype=np.uint8)
        bgr_frame = cv2.imdecode(jpeg_array, cv2.IMREAD_COLOR)
        if bgr_frame is None:
            return None, None, None, None

        # 转 RGB 用于推理
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        return frame_id, timestamp, rgb_frame, bgr_frame

    except socket.timeout:
        # 超时是正常的，不打印
        return None, None, None, None
    except Exception as e:
        print(f"[Inference] 接收失败: {e}")
        return None, None, None, None
```

**相比 pickle 的优势**：
- 帧大小从 ~900KB 降至 ~30-50KB（约 20 倍压缩）
- 内存占用显著降低
- 内存复制次数减少
- 消除 pickle 反序列化安全风险
- 支持带 frame_id 的旧帧丢弃策略

**JPEG 质量与性能权衡**：

| JPEG 质量 | 帧大小 | 质量损失 | CPU (编码) | CPU (解码) | 推荐场景 |
|-----------|--------|---------|-----------|-----------|---------|
| 95 | ~80-100KB | 几乎无 | 高 | 中 | 高精度需求 |
| 80 (默认) | ~30-50KB | 可接受 | 中 | 低 | 日常使用 ✓ |
| 60 | ~15-25KB | 明显 | 低 | 很低 | 极低功耗 |

---

## 3. MediaPipe 关键点

### 3.1 Pose 关键点索引

MediaPipe Pose 输出 33 个人体关键点：

| 索引 | 部位 | 用途 |
|------|------|------|
| 0 | 鼻子 (NOSE) | 人脸定位、头部姿态、距离估算 |
| 7 | 左耳 (LEFT_EAR) | 头部姿态判断 |
| 8 | 右耳 (RIGHT_EAR) | 头部姿态判断 |
| 11 | 左肩 (LEFT_SHOULDER) | 姿态分析、躯干判断 |
| 12 | 右肩 (RIGHT_SHOULDER) | 姿态分析、躯干判断 |
| 23 | 左髋 (LEFT_HIP) | 姿态分析、躯干判断 |
| 24 | 右髋 (RIGHT_HIP) | 姿态分析、躯干判断 |

### 3.2 坐标系统

MediaPipe 使用归一化坐标：
- x, y: [0.0, 1.0]，相对于画面宽高
- z: 深度，相对于臀部（归一化单位）
- visibility: [0.0, 1.0]，关键点可见性置信度

转换为像素坐标：
```python
def get_p(landmark, w, h):
    return (landmark.x * w, landmark.y * h)
```

### 3.3 关键点可见性阈值

v4.0 新增可配置的可见性阈值：

```python
landmark_visibility_threshold: 0.5  # 来自 config.yaml
```

只有可见性 > 0.5 的关键点才用于姿态分析，避免因关键点检测失败导致的误判。

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
→ 连续 5 帧未检测到 → 确认离开
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

### 4.2 姿态评分滑动窗口 (v4.0 新增)

从 v3 的"瞬时判断"升级为"滑动窗口平均评分"，避免瞬时抖动导致的误提醒：

```python
class Supervisor:
    def __init__(self, config=None):
        ...
        self._posture_window = deque()  # 存储 (timestamp, score)
        self._window_size_s = config.posture_window_s  # 默认 4.0s

    def _update_posture_window(self, timestamp, score):
        self._posture_window.append((timestamp, score))
        # 清理过期数据
        cutoff = timestamp - self._window_size_s
        while self._posture_window and self._posture_window[0][0] < cutoff:
            self._posture_window.popleft()

    def _get_window_avg_score(self):
        if not self._posture_window:
            return 0.0
        scores = [s for _, s in self._posture_window]
        return sum(scores) / len(scores)
```

**滑动窗口效果**：
- 4 秒窗口，约 40 个评分点（10FPS 推理）
- 平滑瞬时抖动
- 只有持续不良姿态才会触发提醒

### 4.3 状态提醒防抖

避免频繁提醒用户，采用冷却机制：

```
同一类型提醒
→ 触发后开始冷却计时
→ 冷却期内不再重复提醒
→ 冷却期结束后可再次触发
```

**配置**（默认值）：
```yaml
supervision:
  alert_cooldown_s: 45.0  # 45 秒
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
W: 实际人脸宽度（默认 15 cm，可配置）
f: 摄像头焦距（默认 800，可校准）
P: 人脸像素宽度（从 bbox 获取）
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

**代码实现**：
```python
class MediaPipePoseDetector:
    def __init__(self, ...):
        ...
        self.last_valid_distance = None

    def _estimate_distance(self, face_bbox, frame_shape):
        ...
        raw_distance = (self.face_real_width_cm * self.camera_focal_length) / face_bbox_width
        raw_distance = max(self.distance_min, min(self.distance_max, raw_distance))

        # EMA 平滑
        if self.last_valid_distance is None:
            self.last_valid_distance = raw_distance
        else:
            self.last_valid_distance = (
                self.distance_alpha * raw_distance +
                (1 - self.distance_alpha) * self.last_valid_distance
            )

        return self.last_valid_distance, confidence
```

### 5.3 距离置信度 (v4.0 新增)

**问题背景**：Camera Module 3 Wide 广角镜头在画面边缘存在严重畸变，固定焦距的距离估算在边缘区域误差很大。

**解决方案**：v4.0 新增距离置信度（`DistanceConfidence`）分级，LOW 置信度不触发距离提醒。

**置信度判断规则**：

| 置信度 | 判断依据 (人脸 bbox 中心与画面中心距离) | 行为 |
|--------|------------------------------------------|------|
| HIGH | < edge_reject_ratio (40%) | 正常触发提醒 |
| MEDIUM | 40% - 60% | 正常触发提醒 |
| LOW | > 60% | 不触发距离提醒 |

**距离判断代码**：
```python
class Supervisor:
    def on_distance_update(self, distance_cm, confidence, timestamp):
        # LOW 置信度不触发提醒
        if confidence == DistanceConfidence.LOW:
            self.too_close_start = None
            return None

        # 正常逻辑
        if distance_cm is not None and distance_cm < self.config.too_close_threshold_cm:
            if self.too_close_start is None:
                self.too_close_start = timestamp
            else:
                duration = timestamp - self.too_close_start
                if duration > self.config.too_close_duration:
                    if self._should_alert(AlertType.TOO_CLOSE, timestamp):
                        severity = AlertSeverity.SEVERE if distance_cm < 20 else AlertSeverity.MODERATE
                        ...
        else:
            self.too_close_start = None
```

### 5.4 人脸 bbox 估算

由于不启用 Face Mesh（节省资源），人脸 bbox 通过姿态关键点估算：

```python
def _estimate_face_bbox(self, landmarks, frame_shape):
    h, w, _ = frame_shape
    lm = landmarks.landmark
    pose = self.mp_pose.PoseLandmark

    # 使用鼻子位置作为人脸中心
    nose = (lm[pose.NOSE.value].x * w, lm[pose.NOSE.value].y * h)

    # 使用固定比例作为人脸大小
    face_size = int(min(w, h) * 0.25)
    x = max(0, int(nose[0] - face_size / 2))
    y = max(0, int(nose[1] - face_size / 2))

    return (x, y, face_size, face_size)
```

### 5.5 距离校准方法

如需更精确的距离估算，可进行校准：

1. 让人站在已知距离 `D_known` 处（建议 50cm / 100cm 等易测量距离）
2. 运行程序，查看日志或预览显示的 `P_measured`（人脸像素宽度）
3. 计算焦距：`f = (P_measured × D_known) / W`，其中 W=15cm（人脸实际宽度）
4. 更新 `config.yaml` 中的 `distance.camera_focal_length`

**校准建议**：
- 进行 2-3 次不同距离的测量，取平均值
- 让人正对镜头，人脸在画面中心区域（HIGH 置信度）
- 如果使用广角镜头，建议在 50-100cm 范围内校准，此范围误差较小

---

## 6. 姿态分析算法

### 6.1 姿态评分系统 (v4.0 新增)

从 v3 的"0/1 二元判断"升级为"0-100 连续评分"：

```python
def _analyze_pose_metrics(self, landmarks, frame_shape):
    h, w, _ = frame_shape
    lm = landmarks.landmark
    pose = self.mp_pose.PoseLandmark
    vis_thresh = self._pose_cfg["landmark_visibility_threshold"]

    metrics = PoseMetrics()
    issue_score = 0.0  # 累计扣分

    # ========== 1. 肩膀不平 ==========
    if is_visible(pose.LEFT_SHOULDER) and is_visible(pose.RIGHT_SHOULDER):
        shoulder_height_diff = abs(left_shoulder[1] - right_shoulder[1])
        metrics.shoulder_level = shoulder_height_diff

        threshold = h * self._pose_cfg["shoulder_diff_threshold"]
        if shoulder_height_diff > threshold:
            severity = min(1.0, (shoulder_height_diff - threshold) / threshold)
            issue_score += severity * 0.25  # 权重 0.25
            metrics.issues.append("Uneven Shoulders")

    # ========== 2. 低头/驼背 ==========
    if front_facing:
        ear_avg_y = (left_ear[1] + right_ear[1]) / 2
        threshold = h * self._pose_cfg["head_down_threshold"]
        if nose[1] > ear_avg_y + threshold:
            deviation = (nose[1] - ear_avg_y - threshold) / threshold
            severity = min(1.0, deviation)
            issue_score += severity * 0.35  # 权重 0.35
            metrics.issues.append("Head Down/Slouching")

    # ========== 3. 躯干前倾 ==========
    ... (类似逻辑，权重 0.30)

    # ========== 4. 歪头 ==========
    ... (类似逻辑，权重 0.10)

    # ========== 最终评分 ==========
    metrics.posture_score = min(100.0, issue_score * 100)

    # 根据评分确定整体质量
    if issue_score == 0:
        metrics.overall_quality = PoseQuality.EXCELLENT
    elif issue_score < 0.3:
        metrics.overall_quality = PoseQuality.OK
    elif issue_score < 0.6:
        metrics.overall_quality = PoseQuality.NEEDS_ATTENTION
    else:
        metrics.overall_quality = PoseQuality.BAD

    return metrics
```

### 6.2 严重度分级 (v4.0 新增)

根据姿态评分/距离远近，提醒分为三个等级：

```python
class AlertSeverity(Enum):
    MILD = "mild"        # 轻微
    MODERATE = "moderate" # 中等
    SEVERE = "severe"     # 严重
```

**严重度判断规则**：

| 严重度 | 姿态评分 | 距离 | 颜色 |
|--------|---------|------|------|
| MILD | 30-60 | < threshold | 黄色 |
| MODERATE | 60-80 | < threshold - 5 | 橙色 |
| SEVERE | > 80 | < 20 cm | 红色 |

---

## 7. 配置参数 (v4.0)

所有参数统一在 `config.yaml` 中管理，不再散落在代码各处。

### 7.1 摄像头配置 (camera)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| width | 640 | 采集宽度（像素） |
| height | 480 | 采集高度（像素） |
| fps | 20 | 采集帧率 |
| jpeg_quality | 80 | JPEG 质量 (1-100) |
| format | "RGB888" | Picamera2 采集格式 |

### 7.2 网络配置 (network)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| host | "127.0.0.1" | 监听/连接地址 |
| port | 65432 | 监听/连接端口 |
| recv_timeout_s | 5 | 接收超时（秒） |
| send_timeout_s | 30 | 发送超时（秒） |

### 7.3 推理引擎配置 (inference)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| model_complexity | 1 | 模型复杂度 (0=轻量, 1=平衡, 2=准确) |
| min_detection_confidence | 0.5 | 最小检测置信度 |
| min_tracking_confidence | 0.5 | 最小跟踪置信度 |
| analyze_face | false | Face Mesh（开销大，当前未使用输出） |
| inference_fps | 10 | 推理目标帧率 |
| display_fps | 15 | 预览显示目标帧率 |

### 7.4 距离估算配置 (distance)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| face_real_width_cm | 15.0 | 实际人脸宽度（厘米） |
| camera_focal_length | 800.0 | 摄像头焦距（可校准） |
| min_cm | 30.0 | 有效范围下限（厘米） |
| max_cm | 150.0 | 有效范围上限（厘米） |
| smoothing_alpha | 0.3 | EMA 平滑因子 |
| edge_reject_ratio | 0.4 | 边缘区域拒绝比例 |

### 7.5 姿态检测配置 (pose)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| shoulder_diff_threshold | 0.08 | 肩膀不平阈值（画面高度比例） |
| head_down_threshold | 0.07 | 低头阈值（画面高度比例） |
| lean_forward_threshold | 0.25 | 躯干前倾阈值（画面高度比例） |
| landmark_visibility_threshold | 0.5 | 关键点可见性阈值 |
| posture_window_s | 4.0 | 姿态评分滑动窗口（秒） |
| posture_alert_threshold | 60 | 姿态评分触发阈值（0-100） |

### 7.6 监督逻辑配置 (supervision)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| too_close_threshold_cm | 30.0 | 过近距离阈值（厘米） |
| too_close_duration_s | 5.0 | 过近持续多久才提醒（秒） |
| bad_posture_duration_s | 8.0 | 不良姿态持续多久才提醒（秒） |
| max_study_duration_min | 45 | 最大学习时长（分钟） |
| rest_duration_min | 10 | 休息时长（分钟） |
| alert_cooldown_s | 45.0 | 提醒冷却时间（秒） |
| severity_mild_threshold | 30 | 轻微严重度阈值 |
| severity_moderate_threshold | 60 | 中等严重度阈值 |
| severity_severe_threshold | 80 | 严重严重度阈值 |

### 7.7 温控降频配置 (thermal)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| enabled | true | 是否启用温控 |
| temp_warn_c | 65.0 | 温度警告阈值（℃） |
| temp_throttle_c | 75.0 | 温度降频阈值（℃） |
| temp_check_interval_s | 10 | 温度检查间隔（秒） |
| throttle_inference_fps | 8 | 降频时推理帧率 |
| throttle_model_complexity | 0 | 降频时模型复杂度 |

### 7.8 进程管理配置 (process)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_restart_attempts | 3 | 子进程最大重启次数 |
| restart_backoff_base_s | 2 | 重启退避基数（秒） |
| status_log_interval_s | 10 | 状态日志间隔（秒） |

### 7.9 预览配置 (preview)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| enabled | true | 是否启用预览窗口 |
| window_name | "Kid Supervisor" | 预览窗口名称 |

---

## 8. 性能优化

### 8.1 MediaPipe 优化

1. **model_complexity=1**：平衡精度与速度
2. **static_image_mode=False**：启用跟踪模式，比逐帧检测更快
3. **smooth_landmarks=True**：平滑关键点，减少抖动
4. **Face Mesh 默认关闭**：当前未使用其输出，节省 ~50MB 内存和 CPU
5. **温控降频**：CPU > 75°C 时自动降级 model_complexity 和推理帧率

**各 model_complexity 对比**：

| 复杂度 | 推理速度 (树莓派 5) | 内存占用 | 精度 | 场景 |
|--------|-------------------|---------|------|------|
| 0 | ~15-20 FPS | ~80MB | 一般 | 低功耗 / 降频模式 ✓ |
| 1 (默认) | ~10-12 FPS | ~120MB | 良好 | 日常使用 ✓ |
| 2 | ~5-7 FPS | ~180MB | 最佳 | 高精度需求 |

### 8.2 进程调度 (v4.0 重大优化)

**三级帧率解耦**：
- 摄像头采集：20FPS
- MediaPipe 推理：10FPS
- 预览显示：15FPS

**设计优势**：
- 推理/显示频率解耦，显示复用最近一次推理结果
- 帧带 frame_id/timestamp，推理端丢弃积压旧帧
- 性能日志每 10 秒输出（fps、延迟、丢帧率、CPU 温度）

**帧率控制代码**：
```python
# 推理频率控制
if latest_frame is not None and current_time - last_inference_time >= inference_interval:
    # 推理逻辑
    ...

# 显示频率控制
if current_time - last_display_time >= display_interval:
    # 显示逻辑（复用 last_detection）
    ...
```

**旧帧丢弃策略**：
```python
if last_detection is not None and latest_frame_id is not None:
    frame_gap = latest_frame_id - getattr(last_detection, '_frame_id', 0)
    if frame_gap > 2:
        stats_frames_dropped += 1
        # 仍然用最新帧推理（不是旧帧），只是记录了跳过
```

### 8.3 JPEG 编码优化

- 使用 opencv 硬件加速的 JPEG 编码
- 质量 80 作为平衡点
- 相比 RAW 减少 20x 内存/带宽

### 8.4 CPU 温度监控

使用树莓派 `vcgencmd` 命令获取温度：

```python
def get_cpu_temp():
    try:
        result = subprocess.run(
            ['vcgencmd', 'measure_temp'],
            capture_output=True, text=True, timeout=2
        )
        # 输出格式：temp=42.8'C
        temp_str = result.stdout.strip()
        if '=' in temp_str:
            return float(temp_str.split('=')[1].replace("'C", ''))
    except Exception:
        pass
    return None
```

### 8.5 性能统计日志

每 10 秒输出一次性能统计：

```
[Camera Stats] fps=18.6 frames=186 avg_bytes/frame~=10016
[inference] Stats: recv=18.5fps infer=9.8fps latency=42ms dropped=3 temp=62.1'C throttled=False
```

---

## 9. 错误处理

### 9.1 连接断开处理

**摄像头服务器**：
- 检测到连接断开 → 返回等待状态
- 接受新连接 → 继续发送帧
- 不刷屏打印错误（BrokenPipe/ConnectionReset 除外）

**推理客户端**：
- 检测到连接断开 → 清理并退出
- 由主启动器负责重启

### 9.2 子进程自动重启 (v4.0 新增)

主启动器 (`main.py`) 实现了子进程自动重启：

```python
# 主循环监控子进程
while running:
    # 检查摄像头进程
    if camera_proc and camera_proc.poll() is not None:
        restart_counts["camera"] += 1
        if restart_counts["camera"] <= MAX_RESTART_ATTEMPTS:
            backoff = min(RESTART_BACKOFF_BASE * restart_counts["camera"], 10)
            time.sleep(backoff)
            start_camera()

    # 检查推理进程（类似逻辑）
    ...
```

**重启策略**：
- 任一子进程异常退出后自动重启
- 退避策略：重启间隔递增（2s → 4s → 6s → 8s → 10s，上限 10s）
- 最大重启次数：3 次（可通过 `config.yaml` 配置）
- 超过最大次数后整体退出
- systemd 层保留 `Restart=always` 作为最后防线

### 9.3 异常处理策略

| 错误类型 | 处理方式 |
|---------|---------|
| MediaPipe 初始化失败 | 记录错误，退出 |
| MediaPipe 推理失败 | 记录错误，继续尝试下一帧 |
| Socket 连接失败 | 重试连接（推理客户端）/ 等待连接（摄像头服务器） |
| Socket 超时 | 继续循环，不退出 |
| Socket 断开 | 返回等待状态 / 清理退出 |
| 渲染失败 | 忽略错误，不影响主流程 |
| 窗口关闭失败 | try-catch 包裹，不阻止退出 |

---

## 10. 子进程重启与退避策略详解

### 10.1 退避算法

```python
retry_interval = min(restart_backoff_base_s * retry_count, 10)
```

**退避时间表**：

| 重试次数 | 等待时间 |
|---------|---------|
| 1 | 2s |
| 2 | 4s |
| 3 | 6s |
| 4 | 8s |
| 5+ | 10s (上限) |

### 10.2 设计理由

- 避免频繁重启导致资源耗尽
- 给系统时间恢复
- 上限 10s 避免等待太久

---

## 11. 温控降频策略详解

### 11.1 状态机

```
正常 (model 1, 10FPS)
    │
    │ 温度 > 75°C
    ↓
降频 (model 0, 8FPS)
    │
    │ 温度 < 70°C (有 5°C 回差)
    ↓
正常
```

### 11.2 回差设计

- 触发阈值：75°C
- 恢复阈值：70°C
- 5°C 回差避免频繁切换

---

## 12. 预览渲染文本位置 (v4.0 修复重叠)

| 内容 | 位置 (y 坐标，相对于底部) | 字体缩放 | 颜色 |
|------|-------------------------|---------|------|
| 退出提示 | h - 10 | 0.4 | 白色 |
| 距离 | h - 30 | 0.6 | 绿/红 |
| 姿态问题 1 | h - 100 | 0.5 | 红色 |
| 姿态问题 2 | h - 125 | 0.5 | 红色 |
| 姿态问题 3 | h - 150 | 0.5 | 红色 |
| 姿态评分 | h - 180 | 0.5 | 绿/黄/红 |

---

## 13. 预留接口

### 13.1 音频模块 (src/audio/)

预留了音频相关模块，待后续实现：

- `wake_word.py`：唤醒词检测（如 Porcupine / openWakeWord）
- `stt.py`：语音转文字（如 Whisper / Vosk）
- `tts.py`：文字转语音（如 Piper / eSpeak）

### 13.2 通知模块 (src/notifier.py)

预留了通知模块接口，用于：

- 语音提醒（TTS）
- 其他通知方式（如推送）

---

## 14. v3 → v4 升级指南

### 14.1 依赖变化

新增依赖：
```bash
# 两个进程都需要
pip install pyyaml
```

### 14.2 配置文件迁移

v4 使用统一 `config.yaml`，无需修改代码。

### 14.3 接口变更

| 模块 | 变更 | 影响 |
|------|------|------|
| MediaPipePoseDetector.__init__ | 新增 config 参数 | 需要传入加载的 config |
| Supervisor.__init__ | 新增 config 参数 | 需要传入 SupervisionConfig(config) |
| Supervisor.on_posture_update | 参数从 (is_bad, issues) 变为 (pose_metrics) | 需要传递完整 PoseMetrics |
| Supervisor.on_distance_update | 新增 confidence 参数 | 需要传递 DistanceConfidence |

---

*文档版本：v4.0*  
*最后更新：2026-06-02*
