# 架构设计文档

## 1. 架构概述

### 1.1 设计背景

本项目面临一个关键技术约束：**picamera2 与 mediapipe 对 Python 版本的要求冲突**。

- **picamera2**：树莓派官方摄像头库，仅支持系统 Python 3.13（通过 apt 安装）
- **mediapipe**：Google 机器视觉库，Python 3.13 无预编译 wheel，源码编译困难

因此，我们采用**双进程架构**来解决这一冲突。

### 1.2 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Kid Supervisor v3                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────┐    TCP Socket                 │
│  │  摄像头服务器                    │    (localhost:65432)          │
│  │  (系统 Python 3.13)             │◄──────────────────────────┐   │
│  │                                 │                           │   │
│  │  - Picamera2 采集               │                           │   │
│  │  - RGB888 640x480@20FPS         │                           │   │
│  │  - 通过 Socket 发送帧           │                           │   │
│  └─────────────────────────────────┘                           │   │
│                                                                 │   │
│  ┌─────────────────────────────────┐                           │   │
│  │  推理客户端                     │                           │   │
│  │  (Python 3.11 venv)             │───────────────────────────┘   │
│  │                                 │                               │
│  │  - MediaPipe Pose 检测          │                               │
│  │  - 姿态分析与距离估算           │                               │
│  │  - 监督逻辑                     │                               │
│  │  - 预览渲染                     │                               │
│  └─────────────────────────────────┘                               │
│                                                                     │
│  ┌─────────────────────────────────┐                               │
│  │  主启动器                       │                               │
│  │  (main.py)                      │                               │
│  │                                 │                               │
│  │  - 管理两个子进程               │                               │
│  │  - 信号处理与优雅退出           │                               │
│  └─────────────────────────────────┘                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 进程设计

### 2.1 摄像头服务器 (camera_server.py)

**职责**：
- 初始化并管理 Picamera2 摄像头
- 采集 RGB888 格式的视频帧
- 通过 TCP Socket 发送帧数据

**技术栈**：
- Python：系统 Python 3.13
- 库：picamera2, numpy, socket

**配置参数**：

| 参数 | 值 | 说明 |
|------|-----|------|
| FRAME_SIZE | (640, 480) | 采集分辨率 |
| MAX_FPS | 20 | 最大采集帧率 |
| HOST | '127.0.0.1' | 监听地址 |
| PORT | 65432 | 监听端口 |

**通信协议**：

```
┌─────────────────┬──────────────────────────────┐
│  4 字节长度     │  pickle 序列化的 numpy 数组   │
│  (Big Endian)   │  (RGB888, uint8)             │
└─────────────────┴──────────────────────────────┘
```

### 2.2 推理客户端 (inference_client.py)

**职责**：
- 从 Socket 接收视频帧
- 运行 MediaPipe Pose 推理
- 分析姿态和估算距离
- 执行监督逻辑
- 渲染预览画面（可选）

**技术栈**：
- Python：3.11 (venv)
- 库：mediapipe, opencv-python, numpy, socket

**主循环流程**：

```
1. 接收帧
   ↓
2. MediaPipe Pose 检测
   ↓
3. 存在检测防抖
   ↓
4. 姿态分析与距离估算
   ↓
5. 监督逻辑更新
   ↓
6. 渲染预览 / 日志输出
   ↓ (循环)
```

### 2.3 主启动器 (main.py)

**职责**：
- 检查虚拟环境是否存在
- 启动摄像头服务器子进程
- 启动推理客户端子进程
- 信号处理（SIGINT, SIGTERM）
- 优雅退出清理

---

## 3. 模块设计

### 3.1 姿态检测器 (src/vision/pose_detector.py)

**类结构**：

```python
@dataclass
class PoseMetrics:
    head_pitch, head_yaw, head_roll
    torso_lean, shoulder_level
    overall_quality: PoseQuality
    issues: list[str]

@dataclass
class DetectionResult:
    timestamp: float
    success: bool
    pose_landmarks, face_landmarks
    face_bbox: (x,y,w,h)
    estimated_distance_cm: float
    pose_metrics: PoseMetrics

class MediaPipePoseDetector:
    __init__(model_complexity=1, ...)
    detect(frame, timestamp, analyze_face=True, frame_is_rgb=True)
    close()
```

**姿态分析逻辑**：

| 不良姿势 | 判断依据 |
|---------|---------|
| 肩膀不平 | 左右肩膀 y 坐标差 > 画面高度 5% |
| 低头/驼背 | 鼻子 y 坐标 > 耳朵平均 y + 画面高度 3% |
| 身体前倾/趴着 | 肩膀平均 y > 臀部平均 y - 画面高度 15% |

**距离估算原理**：

使用相似三角形原理：
```
距离 = (实际人脸宽度 × 焦距) / 人脸像素宽度

其中：
- 实际人脸宽度：约 15 cm
- 焦距：预设 600（可校准）
- 人脸像素宽度：从 bbox 获取
```

### 3.2 监督逻辑 (src/supervision.py)

**类结构**：

```python
class AlertType(Enum):
    POSTURE_BAD, TOO_CLOSE, BREAK_NEEDED, BREAK_OVER

@dataclass
class Alert:
    alert_type: AlertType
    message: str
    timestamp: float
    details: dict

class SupervisionConfig:
    too_close_threshold_cm: 35.0
    too_close_duration: 3.0
    bad_posture_duration: 5.0
    max_study_duration: 45 * 60
    rest_duration: 10 * 60
    alert_cooldown: 30.0

class StudySession:
    start_time, end_time
    bad_posture_count, too_close_count
    @property duration

class Supervisor:
    on_person_detected(timestamp)
    on_person_left(timestamp)
    on_posture_update(is_bad, issues, timestamp)
    on_distance_update(distance_cm, timestamp)
    check_study_time(timestamp)
```

**状态机**：

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

**渲染内容**：

1. MediaPipe 骨架连线
2. 人脸框
3. 距离显示
4. 姿态问题列表
5. 学习状态（学习中/休息中/等待中）
6. 统计数据（不良姿势次数/过近距离次数）
7. 提醒横幅
8. 操作提示

**颜色定义**（BGR）：

| 用途 | 颜色 |
|------|------|
| 良好状态 | (0, 255, 0) 绿色 |
| 不良状态 | (0, 0, 255) 红色 |
| 警告 | (0, 255, 255) 黄色 |
| 信息 | (255, 255, 255) 白色 |

---

## 4. 目录结构

```
kid_supervisor_v3/
├── main.py                    # 主启动器
├── camera_server.py           # 摄像头服务器
├── inference_client.py        # 推理客户端
├── setup_venv.py              # 虚拟环境设置
├── start.sh                   # 一键启动
├── requirements-camera.txt    # 摄像头端依赖
├── requirements-inference.txt # 推理端依赖
├── src/
│   ├── __init__.py
│   ├── vision/
│   │   ├── __init__.py
│   │   └── pose_detector.py   # 姿态检测器
│   ├── supervision.py         # 监督逻辑
│   ├── preview_renderer.py    # 预览渲染器
│   ├── camera.py              # 旧版摄像头模块
│   ├── simple_detector.py     # 旧版简单检测器
│   ├── notifier.py            # 通知模块（预留）
│   └── audio/                 # 音频模块（预留）
│       ├── __init__.py
│       ├── wake_word.py
│       ├── stt.py
│       └── tts.py
├── docs/                      # 文档目录
│   ├── requirements.md
│   ├── architecture.md
│   ├── technical-details.md
│   ├── deployment.md
│   └── debug-log.md
├── archive/                   # 归档文件
│   └── old_docs/
└── venv_311/                  # Python 3.11 虚拟环境
```

---

## 5. 设计决策记录

### 5.1 双进程架构 vs 其他方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 双进程 + Socket | 兼容性好，解耦，易调试 | 稍高的通信开销 | ✓ 选择 |
| 仅用系统 Python + 换检测库 | 架构简单 | 需重写检测逻辑，可能损失精度 | ✗ |
| 源码编译 MediaPipe for 3.13 | 单进程 | 编译困难，依赖复杂，维护成本高 | ✗ |

### 5.2 通信方式选择

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| TCP Socket | 简单可靠，原生支持 | 需处理序列化 | ✓ 选择 |
| Unix Socket | 更快，仅本地 | 平台相关 | ✗ |
| 共享内存 | 最低延迟 | 同步复杂 | ✗ |

### 5.3 MediaPipe 配置选择

| 参数 | 值 | 原因 |
|------|-----|------|
| model_complexity | 1 | 树莓派 5 可以流畅运行，精度与速度平衡 |
| min_detection_confidence | 0.5 | 平衡召回率和精确率 |
| min_tracking_confidence | 0.5 | 平滑跟踪结果 |

---

*文档版本：v1.0*  
*最后更新：2026-06-01*
