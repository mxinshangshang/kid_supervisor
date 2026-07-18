# 部署运维指南

## 1. 环境要求

1. Raspberry Pi OS
2. 树莓派 5，推荐 8GB
3. 系统 Python 用于 `picamera2`
4. Python 3.11 venv 用于 `mediapipe`

建议：

1. 使用稳定供电
2. 配置有效散热
3. 优先使用 Camera Module 3 Wide

---

## 2. 需求规格

### 2.1 项目目标

系统目标是为儿童书桌学习场景提供一个本地化、非侵入式、可长期运行的监督方案。

核心目标：

1. 检测孩子是否仍在学习位
2. 检测持续性不良姿态
3. 在正面机位下检测过近距离
4. 记录学习时长并提醒休息
5. 在树莓派 5 上长期稳定运行

### 2.2 功能需求

| ID | 功能 | 优先级 | 当前状态 |
|----|------|--------|---------|
| FR-01 | 存在检测与学习状态切换 | P0 | 已实现 |
| FR-02 | 学习时长统计 | P0 | 已实现 |
| FR-03 | 姿态监督 | P0 | 已实现 |
| FR-04 | 正面机位距离提醒 | P0 | 已实现 |
| FR-05 | 姿态/距离/休息提醒 | P1 | 已实现 |
| FR-06 | 双进程自动恢复 | P1 | 已实现 |
| FR-07 | 温控降频 | P1 | 已实现 |
| FR-08 | 集中配置 | P1 | 已实现 |
| FR-09 | 机位模式 `front/side` | P1 | 已实现 |
| FR-10 | SQLite 会话持久化 | P2 | 已实现 |
| FR-11 | 诊断日志（3天保留） | P2 | 已实现 |
| FR-12 | 学习开始/结束拍照 | P2 | 已实现 |
| FR-13 | 飞书通知 | P2 | 已实现 |
| FR-14 | 语音提醒 | P2 | 预留 |
| FR-15 | Web 管理界面 | P3 | 预留 |

### 2.3 非功能需求

| ID | 要求 | 优先级 | 当前状态 |
|----|------|--------|---------|
| NFR-01 | 本地处理，不上传图像 | P0 | 已实现 |
| NFR-02 | 单次监督延迟维持在可接受范围 | P0 | 已实现 |
| NFR-03 | 稳定运行 4 小时以上 | P1 | 目标达成 |
| NFR-04 | 支持自动恢复 | P1 | 已实现 |
| NFR-05 | 支持温控降频 | P1 | 已实现 |
| NFR-06 | 配置化调参 | P1 | 已实现 |
| NFR-07 | 结果可解释 | P1 | 已实现 |

### 2.4 约束条件

1. 目标硬件为树莓派 5
2. 单摄像头输入
3. 不依赖云端服务
4. 优先轻量、稳定、可维护方案

---

## 3. 安装步骤

### 3.1 准备项目

```bash
cd /path/to/kid_supervisor-main
```

### 3.2 创建推理虚拟环境

```bash
python3 setup_venv.py
```

### 3.3 检查依赖

```bash
/usr/bin/python3 -c "import picamera2; import cv2; print('camera ok')"
venv_311/bin/python -c "import mediapipe; import cv2; print('inference ok')"
```

---

## 4. 配置文件

项目使用统一配置文件 `config.yaml`。

说明：

1. 若 `config.yaml` 缺失，程序会打印提示并回退到默认配置
2. 正式部署建议始终保留显式配置文件，便于追踪参数来源

关键配置段：

1. `camera`
2. `network`
3. `inference`
4. `distance`
5. `pose`
6. `supervision`
7. `thermal`
8. `process`
9. `preview`
10. `storage`
11. `notifier`

### 4.1 摄像头翻转配置

新增 v4.2：

```yaml
camera:
  camera_num: 0
  hflip: false
  vflip: true
```

---

## 5. 推荐配置

### 5.1 正面机位

```yaml
pose:
  camera_view: front
```

适合：

1. 摄像头在屏幕上方
2. 摄像头在桌前偏上方

### 5.2 侧面机位

```yaml
pose:
  camera_view: side
```

适合：

1. 摄像头在座位侧面
2. 主要关注前倾和趴桌

---

## 6. 常用调参

### 6.1 降低系统负载

```yaml
camera:
  width: 480
  height: 360
  fps: 15
  jpeg_quality: 70

inference:
  inference_fps: 8
  display_fps: 10
```

### 6.2 调整姿态灵敏度

```yaml
pose:
  posture_alert_threshold: 65
  shoulder_roll_degree_threshold: 8.0
  head_down_ratio_threshold: 0.16
  lean_forward_ratio_threshold: 0.12
  head_forward_ratio_threshold: 0.12
  desk_proximity_ratio_threshold: 0.18

supervision:
  bad_posture_duration_s: 10.0
  posture_recovery_s: 2.0
```

### 6.3 调整距离提醒

```yaml
supervision:
  too_close_threshold_cm: 32.0
  too_close_duration_s: 5.0
  distance_recovery_s: 1.5

distance:
  edge_reject_ratio: 0.35
  too_close_relative_scale: 1.25
  prefer_relative_baseline: false
```

### 6.4 调整重启恢复策略

```yaml
process:
  status_log_interval_s: 10
```

### 6.5 飞书通知配置

```yaml
notifier:
  console_enabled: true
  audio_enabled: false
  feishu_enabled: true
  feishu_webhook: ""  # 可选
  feishu_secret: ""   # 可选
  alert_cooldown_s: 45
```

说明：
- 如果 `feishu_webhook` 为空，会尝试复用 OpenClaw 的飞书配置
- 照片会在告警、学习开始、学习结束时发送

---

## 7. 工具使用

### 7.1 列出摄像头

新增 v4.2：

```bash
/usr/bin/python3 list_cameras.py
```

用于选择 `camera.camera_num`。

### 7.2 距离校准

仅建议在正面机位下进行。

```bash
/usr/bin/python3 calibrate_distance.py
```

流程：

1. 孩子正对摄像头
2. 坐在已知距离处，例如 `50cm`
3. 稳定保持 2-3 秒
4. 按 `c`
5. 输入真实距离
6. 工具自动写入 `config.yaml`

---

## 8. 启动方式

### 8.1 主启动器

```bash
/usr/bin/python3 main.py
```

### 8.2 无头模式

```bash
/usr/bin/python3 main.py --no-preview
```

### 8.3 分别启动调试

终端 1：

```bash
/usr/bin/python3 camera_server.py
```

终端 2：

```bash
venv_311/bin/python inference_client.py
```

---

## 9. 数据持久化

### 9.1 会话数据库

默认开启 SQLite：

```yaml
storage:
  enabled: true
  sqlite_path: data/kid_supervisor.db
```

保存内容：

1. 学习开始时间
2. 学习结束时间
3. 学习时长
4. 坏姿态次数
5. 过近次数
6. 机位模式

说明：

数据库层会对同一会话做去重更新，避免重复退出时产生重复记录。

### 9.2 诊断日志数据库

新增 v4.2：

默认位置：`data/diagnostic_log.db`

自动清理：保留最近 3 天数据。

查询方式：

```python
from src.diagnostic_log import DiagnosticLogger

logger = DiagnosticLogger("data/diagnostic_log.db")

# 查询最近告警
alerts = logger.query_alerts(limit=10)

# 查询某段时间的帧日志
logs = logger.query_logs(start_time=time.time() - 3600, limit=100)

# 强制清理过期数据
logger.force_cleanup()
```

### 9.3 照片保存路径

默认：`data/` 目录

照片命名：
- `alert_{timestamp}.jpg`
- `start_{timestamp}.jpg`
- `end_{timestamp}.jpg`

---

## 10. 故障排查

### 10.1 摄像头无法启动

检查：

```bash
libcamera-hello
/usr/bin/python3 -c "from picamera2 import Picamera2; print('ok')"
```

列出可用摄像头：

```bash
/usr/bin/python3 list_cameras.py
```

### 10.2 推理端依赖缺失

检查：

```bash
venv_311/bin/python -c "import mediapipe; import cv2; print('ok')"
```

### 10.3 端口占用

检查并处理占用 `65432` 的进程。

### 10.4 预览不显示

可能原因：

1. 没有图形环境
2. `DISPLAY` 未设置
3. 使用了 `--no-preview`

### 10.5 距离不准

先确认：

1. 使用的是正面机位
2. 人脸位于画面中央
3. 已执行校准工具

### 10.6 通知照片颜色反转

v4.2 已修复。如果仍有问题：

1. 确认使用的是最新版本
2. 检查 `save_photo()` 函数没有额外颜色转换

### 10.7 诊断日志过大

诊断日志默认保留 3 天，每帧都记录会占用一定空间。

如需调整：

修改 `DiagnosticLogger` 初始化参数 `retention_days`，或定期调用 `force_cleanup()`。

---

## 11. 验收重点

部署后建议按顺序验证：

1. 正常进入/离开学习位能否稳定切换
2. 正面机位下距离值是否随前后移动单调变化
3. 侧面机位下前倾和趴桌是否更容易触发
4. 告警消息是否只显示最严重的一个问题
5. 飞书通知是否正常收到且照片颜色正确
6. 学习开始/结束是否有照片通知
7. 无头模式下统计日志是否持续稳定输出
8. 诊断日志是否正常记录（可通过简单查询验证）

---

## 12. 当前已知边界

1. 光照差时关键点稳定性仍会下降
2. 轻量距离估算仍存在个体差异，需要校准
3. 极端遮挡或极端角度下，结果仍可能波动
4. 诊断日志保留 3 天，占用空间随帧率增长

---

## 13. 当前不纳入范围

当前阶段不纳入：

1. 多摄像头融合
2. Web 管理后台
3. 云端识别
4. 重型模型替换
5. 完整语音交互

原因：这些内容不符合当前版本"树莓派 5 单机稳定监督"的主要目标。
