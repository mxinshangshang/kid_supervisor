# 部署与配置指南

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

## 2. 安装步骤

### 2.1 准备项目

```bash
cd /path/to/kid_supervisor-main
```

### 2.2 创建推理虚拟环境

```bash
python3 setup_venv.py
```

### 2.3 检查依赖

```bash
/usr/bin/python3 -c "import picamera2; import cv2; print('camera ok')"
venv_311/bin/python -c "import mediapipe; import cv2; print('inference ok')"
```

---

## 3. 配置文件

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

---

## 4. 推荐配置

### 4.1 正面机位

```yaml
pose:
  camera_view: front
```

适合：

1. 摄像头在屏幕上方
2. 摄像头在桌前偏上方

### 4.2 侧面机位

```yaml
pose:
  camera_view: side
```

适合：

1. 摄像头在座位侧面
2. 主要关注前倾和趴桌

---

## 5. 常用调参

### 5.1 降低系统负载

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

### 5.2 调整姿态灵敏度

```yaml
pose:
  posture_alert_threshold: 65
  shoulder_diff_threshold: 0.10
  head_down_threshold: 0.08
  lean_forward_threshold: 0.25

supervision:
  bad_posture_duration_s: 10.0
```

### 5.3 调整距离提醒

```yaml
supervision:
  too_close_threshold_cm: 32.0
  too_close_duration_s: 5.0

distance:
  edge_reject_ratio: 0.35
```

### 5.4 调整重启恢复策略

```yaml
process:
  max_restart_attempts: 3
  restart_backoff_base_s: 2
  restart_reset_after_s: 60
  status_log_interval_s: 10
```

---

## 6. 启动方式

### 6.1 主启动器

```bash
/usr/bin/python3 main.py
```

### 6.2 无头模式

```bash
/usr/bin/python3 main.py --no-preview
```

### 6.3 分别启动调试

终端 1：

```bash
/usr/bin/python3 camera_server.py
```

终端 2：

```bash
venv_311/bin/python inference_client.py
```

---

## 7. 距离校准

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

## 8. 数据持久化

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

---

## 9. 故障排查

### 9.1 摄像头无法启动

检查：

```bash
libcamera-hello
/usr/bin/python3 -c "from picamera2 import Picamera2; print('ok')"
```

### 9.2 推理端依赖缺失

检查：

```bash
venv_311/bin/python -c "import mediapipe; import cv2; print('ok')"
```

### 9.3 端口占用

检查并处理占用 `65432` 的进程。

### 9.4 预览不显示

可能原因：

1. 没有图形环境
2. `DISPLAY` 未设置
3. 使用了 `--no-preview`

### 9.5 距离不准

先确认：

1. 使用的是正面机位
2. 人脸位于画面中央
3. 已执行校准工具

---

## 10. 实测建议

部署后建议按顺序验证：

1. 正常进入/离开学习位能否稳定切换
2. 正面机位下距离值是否随前后移动单调变化
3. 侧面机位下前倾和趴桌是否更容易触发
4. 无头模式下统计日志是否持续稳定输出
