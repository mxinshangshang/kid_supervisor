# 架构设计文档

## 1. 架构概述

### 1.1 设计背景

本项目面临一个关键技术约束：**picamera2 与 mediapipe 对 Python 版本的要求冲突**。

- **picamera2**：树莓派官方摄像头库，仅支持系统 Python 3.13（通过 apt 安装）
- **mediapipe**：Google 机器视觉库，Python 3.13 无预编译 wheel，源码编译困难

因此，我们采用**双进程架构**来解决这一冲突。

### 1.2 架构总览 (v4.0)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Kid Supervisor v4.0                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────┐           │
│  │  配置中心 (config.yaml)                                        │           │
│  │  - 摄像头采集参数 (分辨率、帧率、JPEG 质量)                    │           │
│  │  - 网络传输参数 (端口、超时)                                    │           │
│  │  - 推理引擎参数 (模型复杂度、推理/显示帧率)                     │           │
│  │  - 距离估算参数 (焦距、平滑系数、边缘拒绝比例)                 │           │
│  │  - 姿态检测参数 (阈值、滑动窗口大小)                            │           │
│  │  - 监督逻辑参数 (提醒阈值、冷却时间、严重度分级)               │           │
│  │  - 温控降频参数 (温度阈值、降级策略)                            │           │
│  │  - 进程管理参数 (最大重启次数、退避策略)                        │           │
│  └─────────────────────────────────────────────────────────────────┘           │
│                                                                                 │
│  ┌─────────────────────────────────┐    TCP Socket (带帧序号/时间戳)           │
│  │  摄像头服务器                    │    (localhost:65432)                      │
│  │  (系统 Python 3.13)             │◄──────────────────────────────────────┐  │
│  │                                 │                                       │  │
│  │  - Picamera2 采集               │                                       │  │
│  │  - RGB888 640x480@20FPS         │                                       │  │
│  │  - JPEG 压缩 (质量可调)         │                                       │  │
│  │  - 通过 Socket 发送帧 (带序号)  │                                       │  │
│  │  - 性能统计 (fps、发送字节数)   │                                       │  │
│  └─────────────────────────────────┘                                       │  │
│                                                                              │  │
│  ┌─────────────────────────────────┐                                       │  │
│  │  推理客户端                     │───────────────────────────────────────┘  │
│  │  (Python 3.11 venv)             │                                          │
│  │                                 │                                          │
│  │  - 接收 JPEG 帧，丢弃旧帧       │                                          │
│  │  - MediaPipe Pose 检测 (10FPS) │                                          │
│  │  - 姿态分析 + 滑动窗口评分     │                                          │
│  │  - 距离估算 + 置信度分级        │                                          │
│  │  - 温控降频 (CPU > 75°C 降级)  │                                          │
│  │  - 监督逻辑 (严重度分级)        │                                          │
│  │  - 预览渲染 (15FPS，复用推理)  │                                          │
│  │  - 性能统计 (recv/infer fps)   │                                          │
│  └─────────────────────────────────┘                                          │
│                                                                                 │
│  ┌─────────────────────────────────┐                                           │
│  │  主启动器                       │                                           │
│  │  (main.py)                      │                                           │
│  │                                 │                                           │
│  │  - 管理两个子进程生命周期       │                                           │
│  │  - 子进程异常自动重启 (带退避) │                                           │
│  │  - 最大重启次数限制             │                                           │
│  │  - 信号处理与优雅退出           │                                           │
│  └─────────────────────────────────┘                                           │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 进程设计

### 2.1 摄像头服务器 (camera_server.py)

**职责**：
- 初始化并管理 Picamera2 摄像头
- 采集 RGB888 格式的视频帧
- JPEG 压缩帧数据（质量可调）
- 通过 TCP Socket 发送帧（带帧序号和时间戳）
- 定期输出性能统计

**技术栈**：
- Python：系统 Python 3.13
- 库：picamera2, opencv-python, numpy, pyyaml, socket

**配置参数**（从 config.yaml 加载）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| camera.width | 640 | 采集宽度 |
| camera.height | 480 | 采集高度 |
| camera.fps | 20 | 最大采集帧率 |
| camera.jpeg_quality | 80 | JPEG 质量 (1-100) |
| camera.format | 'RGB888' | 采集格式 |
| network.host | '127.0.0.1' | 监听地址 |
| network.port | 65432 | 监听端口 |
| network.send_timeout_s | 30 | 发送超时（秒） |

**通信协议 (v4.0)**：

```
┌─────────────┬──────────────────┬──────────────┬──────────────────┐
│  4 字节     │    8 字节        │   4 字节     │  变长字节        │
│  frame_id   │   timestamp      │  jpeg_len    │  jpeg_data       │
│ (BigEndian) │  (double)        │ (BigEndian)  │  (JPEG 压缩帧)   │
└─────────────┴──────────────────┴──────────────┴──────────────────┘
```

- **frame_id**：单调递增的帧序号，用于接收端丢弃旧帧
- **timestamp**：帧采集时间（Unix 时间戳）
- **jpeg_len**：JPEG 数据长度
- **jpeg_data**：JPEG 编码的视频帧

**设计亮点**：
- JPEG 压缩相比 pickle RAW，帧大小从 ~900KB 降至 ~30-50KB（20x 压缩）
- 带 frame_id 允许接收端选择性丢弃旧帧
- 带宽和内存占用大幅降低

### 2.2 推理客户端 (inference_client.py)

**职责**：
- 从 Socket 接收 JPEG 帧（带超时）
- 解码并转换格式
- 按设定频率运行 MediaPipe Pose 推理
- 分析姿态（滑动窗口评分 + 严重度分级）
- 估算距离（带置信度 + 边缘区域拒绝）
- 温控降频（CPU 温度过高时自动降低推理负载）
- 监督逻辑判断
- 预览渲染（复用最近推理结果，比推理帧率高）
- 定期输出性能统计

**技术栈**：
- Python：3.11 (venv)
- 库：mediapipe, opencv-python, numpy, pyyaml, socket, subprocess

**配置参数**（从 config.yaml 加载）：

| 参数分类 | 参数 | 默认值 | 说明 |
|---------|------|--------|------|
| inference | model_complexity | 1 | 模型复杂度 (0/1/2) |
| inference | min_detection_confidence | 0.5 | 最小检测置信度 |
| inference | min_tracking_confidence | 0.5 | 最小跟踪置信度 |
| inference | analyze_face | false | 是否启用 Face Mesh |
| inference | inference_fps | 10 | 推理目标帧率 |
| inference | display_fps | 15 | 显示目标帧率 |
| thermal | enabled | true | 是否启用温控 |
| thermal | temp_warn_c | 65.0 | 温度警告阈值 |
| thermal | temp_throttle_c | 75.0 | 温度降频阈值 |
| thermal | temp_check_interval_s | 10 | 温度检查间隔 |
| thermal | throttle_inference_fps | 8 | 降频时推理帧率 |
| thermal | throttle_model_complexity | 0 | 降频时模型复杂度 |

**主循环流程 (v4.0)**：

```
1. 接收帧 (非阻塞，带超时)
   ├─ 成功：更新 latest_frame / latest_frame_id
   └─ 超时：继续循环
   ↓
2. 温度检查 (每 10 秒)
   ├─ 温度 > throttle_c：降频 (推理 10→8 fps, model 1→0)
   ├─ 温度 < throttle_c - 5°C：恢复正常
   └─ 输出温度日志
   ↓
3. 推理 (按 inference_fps 控制频率)
   ├─ 若最新帧 id >> 上次推理帧 id：记录丢帧
   ├─ MediaPipe Pose 检测
   ├─ 姿态分析 + 滑动窗口评分
   ├─ 距离估算 + 置信度判断
   └─ 更新 last_detection
   ↓
4. 存在检测防抖
   ├─ 有人：连续 2 帧 → person_detected = True
   └─ 无人：连续 5 帧 → person_detected = False
   ↓
5. 监督逻辑更新
   ├─ 姿态：滑动窗口评分 > 阈值 + 持续时间 → 提醒
   ├─ 距离：距离 < 阈值 + 置信度 != LOW + 持续时间 → 提醒
   └─ 学习时长：> 45 分钟 → 提醒休息
   ↓
6. 渲染预览 / 日志输出 (按 display_fps 控制频率)
   ├─ 复用 last_detection 结果
   ├─ 无预览模式：每 10 秒输出性能统计
   └─ 预览模式：渲染画面
   ↓ (循环)
```

**设计亮点**：
- 推理/显示帧率解耦：推理 10FPS，显示 15FPS，显示复用推理结果
- 带 frame_id 丢弃旧帧：推理端始终处理最新帧
- 温控降频：树莓派高负载时自动降级，避免过热
- 性能统计：实时监控 recv/infer fps、延迟、丢帧率、CPU 温度

### 2.3 主启动器 (main.py)

**职责**：
- 检查虚拟环境是否存在
- 加载 config.yaml 配置
- 启动摄像头服务器子进程
- 启动推理客户端子进程
- 监控子进程状态，异常自动重启
- 退避策略：重启间隔递增 (2s → 4s → 6s → 8s → 10s)
- 最大重启次数限制：防止无限重启
- 信号处理（SIGINT, SIGTERM）
- 优雅退出清理

**配置参数**（从 config.yaml 加载）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| process.max_restart_attempts | 3 | 子进程最大重启次数 |
| process.restart_backoff_base_s | 2 | 重启退避基数（秒） |
| process.status_log_interval_s | 10 | 状态日志间隔 |

**进程重启策略**：

```
子进程退出 → 检查重启次数
├─ < max_restart_attempts：
│  ├─ 等待 backoff 时间 (2 * retry_count，上限 10s)
│  └─ 重启子进程
└─ >= max_restart_attempts：
   └─ 整体退出，报错
```

**设计亮点**：
- 自动重启：提高系统可用性
- 退避策略：避免频繁重启导致的资源浪费
- 次数限制：防止无限重启耗尽系统资源

---

## 3. 模块设计

### 3.1 姿态检测器 (src/vision/pose_detector.py)

**类结构 (v4.0)**：

```python
class PoseQuality(Enum):
    EXCELLENT, OK, NEEDS_ATTENTION, BAD

class DistanceConfidence(Enum):
    HIGH, MEDIUM, LOW  # 新增

@dataclass
class PoseMetrics:
    head_pitch, head_yaw, head_roll
    torso_lean, shoulder_level
    posture_score: float  # 新增：0-100 连续评分
    overall_quality: PoseQuality
    issues: list[str]

@dataclass
class DetectionResult:
    timestamp: float
    success: bool
    pose_landmarks, face_landmarks
    face_bbox: (x,y,w,h)
    estimated_distance_cm: float
    distance_confidence: DistanceConfidence  # 新增
    pose_metrics: PoseMetrics

class MediaPipePoseDetector:
    __init__(model_complexity=1, ..., config=None)  # 新增：config 参数
    detect(frame, timestamp, analyze_face=False, frame_is_rgb=True)
    set_model_complexity(complexity)  # 新增：动态切换
    close()
```

**姿态分析逻辑 (v4.0)**：

从 v3 的 "0/1 二元判断" 升级为 "0-100 连续评分 + 滑动窗口平均"：

| 不良姿势 | 判断依据 | 阈值 (画面高度比例) |
|---------|---------|---------------------|
| 肩膀不平 | 左右肩膀 y 坐标差 | 8% |
| 低头/驼背 | 鼻子 y 坐标 > 耳朵平均 y | 7% |
| 身体前倾/趴着 | 肩膀平均 y > 臀部平均 y | 25% |
| 歪头 | 耳朵连线倾斜角度 | > 15° |
| 驼背 (新增) | 鼻子相对于肩膀-臀部连线偏移 | > 肩宽 30% |

**评分规则**：
- 每项问题按超出阈值的程度计算严重性 (0-1)
- 加权求和：肩膀(0.25) + 低头(0.35) + 前倾(0.30) + 歪头(0.10)
- 最终得分：0-100，越高越差
- 滑动窗口平均：4 秒窗口，避免瞬时抖动

**距离估算原理 (v4.0)**：

使用相似三角形原理 + EMA 平滑 + 置信度分级：

```
距离 = (实际人脸宽度 × 焦距) / 人脸像素宽度

其中：
- 实际人脸宽度：默认 15 cm (可配置)
- 焦距：默认 800 (可校准)
- 人脸像素宽度：从 bbox 获取
- EMA 平滑系数：0.3 (可配置)
- 有效范围：30-150 cm
```

**距离置信度分级 (新增)**：

解决广角镜头边缘区域距离估算不准的问题：

| 置信度 | 判断依据 (人脸 bbox 中心与画面中心距离) | 行为 |
|--------|------------------------------------------|------|
| HIGH | < edge_reject_ratio (40%) | 正常触发提醒 |
| MEDIUM | 40% - 60% | 正常触发提醒 |
| LOW | > 60% | 不触发距离提醒 |

### 3.2 监督逻辑 (src/supervision.py)

**类结构 (v4.0)**：

```python
class AlertType(Enum):
    POSTURE_BAD, TOO_CLOSE, BREAK_NEEDED, BREAK_OVER

class AlertSeverity(Enum):  # 新增
    MILD, MODERATE, SEVERE

@dataclass
class Alert:
    alert_type: AlertType
    message: str
    timestamp: float
    severity: AlertSeverity  # 新增
    details: dict

class SupervisionConfig:
    # 从 config.yaml 加载所有参数
    def __init__(self, config=None): ...

class StudySession:
    start_time, end_time
    bad_posture_count, too_close_count
    @property duration

class Supervisor:
    __init__(config=None)  # 新增：config 参数
    on_person_detected(timestamp)
    on_person_left(timestamp)
    on_posture_update(pose_metrics, timestamp)  # 签名变更
    on_distance_update(distance_cm, confidence, timestamp)  # 签名变更
    check_study_time(timestamp)
```

**严重度分级 (新增)**：

根据姿态评分/距离远近，提醒分为三个等级：

| 严重度 | 姿态评分 | 距离 | 颜色 |
|--------|---------|------|------|
| MILD | 30-60 | < threshold | 黄色 |
| MODERATE | 60-80 | < threshold - 5 | 橙色 |
| SEVERE | > 80 | < 20 cm | 红色 |

**触发条件 (v4.0)**：

| 提醒类型 | 触发条件 |
|---------|---------|
| POSTURE_BAD | 滑动窗口平均评分 > posture_alert_threshold (60) + 持续 bad_posture_duration_s (8s) + 冷却期已过 |
| TOO_CLOSE | 距离 < too_close_threshold_cm (30cm) + 距离置信度 != LOW + 持续 too_close_duration_s (5s) + 冷却期已过 |
| BREAK_NEEDED | 学习时长 > max_study_duration_min (45min) |
| BREAK_OVER | 休息时长 > rest_duration_min (10min) |

**状态机 (v4.0 无变化)**：

```
┌─────────┐  人脸检测   ┌──────────────┐
│ Waiting ├────────────►│  Studying    │
└─────────┘             └──────┬───────┘
    ▲                         │
    │ 人脸消失                │ 学习超时
    │                         │
    │                         ▼
    │                   ┌──────────┐
    └───────────────────┤  Resting │
      休息结束/人脸消失 └──────────┘
```

### 3.3 预览渲染器 (src/preview_renderer.py)

**渲染内容 (v4.0)**：

1. MediaPipe 骨架连线
2. 人脸框
3. 距离显示（带置信度标记 "?" 表示 LOW）
4. 姿态问题列表（最多 3 个）
5. 姿态评分 (0-100)
6. 学习状态（学习中/休息中/等待中）
7. 统计数据（不良姿势次数/过近距离次数）
8. 提醒横幅（按严重度着色）
9. 操作提示

**颜色定义**（BGR）：

| 用途 | 颜色 |
|------|------|
| 良好状态 | (0, 255, 0) 绿色 |
| 轻微警告 (MILD) | (0, 200, 200) 黄色 |
| 中等警告 (MODERATE) | (0, 100, 200) 橙色 |
| 严重警告 (SEVERE) / 不良状态 | (0, 0, 255) 红色 |
| 警告 | (0, 255, 255) 黄色 |
| 信息 | (255, 255, 255) 白色 |

**文字位置 (v4.0 修复重叠)**：

| 内容 | 位置 (y 坐标，相对于底部) |
|------|-------------------------|
| 退出提示 | h - 10 |
| 距离 | h - 30 |
| 姿态问题 | h - 100, h - 125, h - 150 |
| 姿态评分 | h - 180 |

---

## 4. 配置文件 (config.yaml)

v4.0 新增统一配置文件，所有可调参数集中管理：

```yaml
# 摄像头采集
camera:
  width: 640
  height: 480
  fps: 20
  jpeg_quality: 80
  format: "RGB888"

# 网络传输
network:
  host: "127.0.0.1"
  port: 65432
  recv_timeout_s: 5
  send_timeout_s: 30

# 推理引擎
inference:
  model_complexity: 1
  min_detection_confidence: 0.5
  min_tracking_confidence: 0.5
  analyze_face: false
  inference_fps: 10
  display_fps: 15

# 距离估算
distance:
  face_real_width_cm: 15.0
  camera_focal_length: 800.0
  min_cm: 30.0
  max_cm: 150.0
  smoothing_alpha: 0.3
  edge_reject_ratio: 0.4

# 姿态检测
pose:
  shoulder_diff_threshold: 0.08
  head_down_threshold: 0.07
  lean_forward_threshold: 0.25
  landmark_visibility_threshold: 0.5
  posture_window_s: 4.0
  posture_alert_threshold: 60

# 监督逻辑
supervision:
  too_close_threshold_cm: 30.0
  too_close_duration_s: 5.0
  bad_posture_duration_s: 8.0
  max_study_duration_min: 45
  rest_duration_min: 10
  alert_cooldown_s: 45.0
  severity_mild_threshold: 30
  severity_moderate_threshold: 60
  severity_severe_threshold: 80

# 温控降频
thermal:
  enabled: true
  temp_warn_c: 65.0
  temp_throttle_c: 75.0
  temp_check_interval_s: 10
  throttle_inference_fps: 8
  throttle_model_complexity: 0

# 进程管理
process:
  max_restart_attempts: 3
  restart_backoff_base_s: 2
  status_log_interval_s: 10

# 预览
preview:
  enabled: true
  window_name: "Kid Supervisor"
```

---

## 5. 目录结构

```
kid_supervisor_v3/
├── main.py                    # 主启动器 (v4: 自动重启)
├── camera_server.py           # 摄像头服务器 (v4: JPEG/frame_id)
├── inference_client.py        # 推理客户端 (v4: 帧率解耦/温控)
├── config.yaml                # 统一配置文件 (v4 新增)
├── setup_venv.py              # 虚拟环境设置
├── start.sh                   # 一键启动
├── start_headless.sh          # 无预览启动
├── start_sys.sh               # 系统启动脚本
├── requirements-camera.txt    # 摄像头端依赖 (v4: 新增 pyyaml)
├── requirements-inference.txt # 推理端依赖 (v4: 新增 pyyaml)
├── requirements.txt           # 完整依赖
├── src/
│   ├── __init__.py
│   ├── vision/
│   │   ├── __init__.py
│   │   └── pose_detector.py   # 姿态检测器 (v4: 置信度/评分)
│   ├── supervision.py         # 监督逻辑 (v4: 严重度/滑动窗口)
│   ├── preview_renderer.py    # 预览渲染器 (v4: 配置化)
│   └── (旧版模块已归档)
├── docs/                      # 文档目录
│   ├── requirements.md
│   ├── architecture.md
│   ├── technical-details.md
│   ├── deployment.md
│   └── debug-log.md
└── venv_311/                  # Python 3.11 虚拟环境
```

---

## 6. 设计决策记录

### 6.1 双进程架构 vs 其他方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 双进程 + Socket | 兼容性好，解耦，易调试 | 稍高的通信开销 | ✓ 选择 |
| 仅用系统 Python + 换检测库 | 架构简单 | 需重写检测逻辑，可能损失精度 | ✗ |
| 源码编译 MediaPipe for 3.13 | 单进程 | 编译困难，依赖复杂，维护成本高 | ✗ |

### 6.2 通信方式选择 (v4.0 重大更新)

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| JPEG + Socket (v4) | 压缩率高 (20x)，低内存，带 frame_id | 稍高的编码/解码 CPU | ✓ 选择 |
| Pickle RAW + Socket (v3) | 简单，无质量损失 | 内存占用大 (900KB/帧)，带宽高 | ✗ |
| Unix Socket | 更快，仅本地 | 平台相关 | ✗ |
| 共享内存 | 最低延迟 | 同步复杂 | ✗ |

**v3 → v4 收益**：
- 内存占用：900KB → 30-50KB (20x 降低)
- 带宽占用：降低 20x
- 支持带 frame_id 的旧帧丢弃策略

### 6.3 MediaPipe 配置选择

| 参数 | 默认值 | 降级值 | 原因 |
|------|--------|--------|------|
| model_complexity | 1 | 0 | 树莓派 5 正常模式下流畅运行，精度与速度平衡；降频时降级到 0 节省 CPU |
| min_detection_confidence | 0.5 | 0.5 | 平衡召回率和精确率 |
| min_tracking_confidence | 0.5 | 0.5 | 平滑跟踪结果 |

### 6.4 温控降频策略 (v4.0 新增)

树莓派 5 在高负载下易过热，设计温控策略：

- 温度 < 65°C：正常模式 (model 1, 10FPS)
- 65-75°C：警告日志
- > 75°C：降频模式 (model 0, 8FPS)
- < 70°C：恢复正常

### 6.5 距离置信度 (v4.0 新增)

广角镜头边缘区域畸变严重，固定焦距的距离估算不准：

- 方案 A：畸变校正 → 复杂，需标定
- 方案 B：边缘区域拒绝 → 简单，实用 ✓ 选择

最终选择方案 B，通过人脸在画面中的位置判断距离置信度，LOW 置信度不触发提醒。

---

## 7. v3 → v4 主要改进总结

| 方面 | v3 | v4 |
|------|-----|-----|
| 配置管理 | 散落在代码各处 | 集中在 config.yaml |
| 帧传输 | Pickle RAW (900KB/帧) | JPEG 压缩 (30-50KB/帧) |
| 帧同步 | 无 | 带 frame_id/timestamp，支持丢弃旧帧 |
| 推理/显示帧率 | 耦合，同频 | 解耦 (10FPS 推理，15FPS 显示) |
| 姿态判断 | 二元 (0/1) | 连续评分 (0-100) + 滑动窗口 |
| 距离估算 | 无置信度 | 置信度分级 + 边缘区域拒绝 |
| 提醒分级 | 无 | MILD/MODERATE/SEVERE 三级 |
| 温控降频 | 无 | CPU > 75°C 自动降级 |
| 进程管理 | 无自动重启 | 自动重启 + 退避策略 + 次数限制 |
| 性能统计 | 无 | recv/infer fps、延迟、丢帧率、CPU 温度 |

---

*文档版本：v4.0*  
*最后更新：2026-06-02*
