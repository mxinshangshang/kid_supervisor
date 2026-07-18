# 技术实现细节

## 1. 颜色空间

系统采用以下颜色路径：

1. 摄像头采集：RGB888
2. JPEG 编码前：RGB -> BGR
3. JPEG 解码后：BGR -> RGB
4. 推理与预览统一使用 RGB
5. 保存照片时直接使用 RGB，不做额外转换

---

## 2. 帧传输协议

协议格式：

```text
[4B frame_id][8B timestamp][4B jpeg_len][jpeg_data]
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `frame_id` | uint32 | 单调递增帧序号 |
| `timestamp` | double | 采集时间戳 |
| `jpeg_len` | uint32 | JPEG 数据长度 |
| `jpeg_data` | bytes | JPEG 编码帧 |

说明：

1. 摄像头端按真实字节数统计发送量
2. 推理端只保留最新帧，避免推理积压
3. 丢帧统计仅在接收线程中累计，避免重复计数

---

## 3. 推理流程

当前推理进程采用"接收线程 + 主循环"结构。

### 3.1 接收线程

职责：

1. 从 socket 持续拉取完整帧
2. 解码 JPEG
3. 将最新 RGB 帧写入共享缓冲
4. 记录超时、重连和解码失败统计
5. 在退出或重连时通过锁保护 socket 生命周期

### 3.2 主循环

职责：

1. 周期检查 CPU 温度
2. 按 `inference_fps` 运行姿态检测
3. 按 `display_fps` 刷新预览
4. 在 headless 模式下输出统计日志
5. 调用诊断日志记录每帧结果

---

## 4. 距离估算

### 4.1 当前方案

当前版本不再使用"鼻子中心 + 固定方框"的伪人脸框。

改为：

1. 使用头部关键点估计预览框 `face_bbox`
2. 使用更窄的 `distance_bbox` 作为距离输入
3. 使用相似三角形进行轻量估算
4. 用 EMA 做平滑
5. 用画面中心偏移做置信度分级

距离估算公式：

```text
distance = (face_real_width_cm * camera_focal_length) / face_width_px
```

### 4.2 置信度

根据头部框中心与画面中心的偏移计算：

1. `HIGH`
2. `MEDIUM`
3. `LOW`

仅正面机位参与距离提醒。

### 4.3 限制

该方案属于轻量近似测距，适合当前硬件条件。若后续需要更高精度，可替换为轻量真实人脸框检测。

---

## 5. 机位模式

### 5.1 正面模式 `front`

检测重点：

1. `低头`
2. `歪头`
3. `前倾`
4. `双肩不平`
5. 距离过近

### 5.2 侧面模式 `side`

检测重点：

1. `头前伸`
2. `趴桌`
3. `前倾`

说明：

侧面机位下不再主打精确距离判断。

---

## 6. 姿态评分

当前姿态评分是可配置的加权规则系统，而不是黑盒分类器。

配置位置：

```yaml
pose:
  weights:
    uneven_shoulders: 20.0
    head_down: 35.0
    head_tilt: 10.0
    leaning_forward: 30.0
    head_forward: 30.0
    desk_proximity: 35.0
```

设计原则：

1. 指标尽量少
2. 原因可解释
3. 可按真实书桌环境调参

### 6.1 问题详情记录

从 v4.2 开始，`PoseMetrics` 新增 `issue_details` 字段，保存每个问题的原始计算数据：

```python
metrics.issue_details = {
    "低头": {
        "score": 35.0,
        "raw_ratio": 0.18,
        "threshold": 0.16
    },
    ...
}
```

这用于诊断日志回溯和告警时选择最严重问题。

---

## 7. 存在检测防抖

当前实现已配置化：

```yaml
supervision:
  presence_enter_frames: 2
  presence_exit_frames: 5
  presence_grace_s: 2.0
```

说明：

1. 连续检测到人达到阈值后进入学习状态
2. 连续丢失达到阈值且超过宽限时间后退出学习状态
3. 短时遮挡、低头、手部穿插不应立刻导致离开状态切换

---

## 8. 冷却与持续时间

监督逻辑采用两层保护：

1. 持续时间门槛
2. 提醒冷却时间

例如：

1. 姿态不良必须持续超过 `bad_posture_duration_s`
2. 姿态恢复后还需连续稳定超过 `posture_recovery_s` 才清除坏姿态状态
3. 距离过近必须持续超过 `too_close_duration_s`
4. 距离恢复后还需连续稳定超过 `distance_recovery_s` 才清除过近状态
5. 同类提醒在 `alert_cooldown_s` 内不会重复触发

对于低置信度距离读数，还加入了短宽限时间，避免一两帧波动直接打断距离累计。

---

## 9. 告警消息

从 v4.2 开始：

1. 问题标签直接用中文在 `pose_detector.py` 中生成（不再翻译）
2. 告警只显示得分最高的一个问题
3. 消息格式：`{问题} ({严重度})`，例如：`低头 (中度)`

---

## 10. 诊断日志

新增 `src/diagnostic_log.py` - `DiagnosticLogger` 类。

### 10.1 功能

1. 记录每帧完整算法结果（检测、姿势、距离、监督器状态）
2. 记录告警事件（含照片路径）
3. 记录学习会话状态变化
4. 自动清理 3 天前旧数据
5. 提供查询接口 `query_logs()` / `query_alerts()`

### 10.2 数据表

- `diagnostic_logs` - 逐帧数据
- `alert_events` - 告警事件（含照片路径）
- `session_events` - 会话状态变化

### 10.3 使用示例

```python
from diagnostic_log import DiagnosticLogger

logger = DiagnosticLogger("data/diagnostic_log.db")

# 查询最近告警
alerts = logger.query_alerts(limit=10)

# 查询某段时间的帧日志
logs = logger.query_logs(start_time=time.time() - 3600, limit=100)
```

---

## 11. 温控策略

当前温度读取优先走：

```text
/sys/class/thermal/thermal_zone0/temp
```

策略：

1. 高于 `temp_throttle_c` 时降频
2. 推理帧率降到 `throttle_inference_fps`
3. 模型复杂度切换到 `throttle_model_complexity`
4. 温度回落后恢复正常

恢复迟滞通过 `thermal.throttle_recover_margin_c` 配置。

---

## 12. 最小持久化

当前通过 SQLite 保存会话：

表：`study_sessions`

字段：

1. `started_at`
2. `ended_at`
3. `duration_s`
4. `bad_posture_count`
5. `too_close_count`
6. `camera_view`

数据库层通过唯一索引和 upsert 避免重复写入同一会话。

这为后续统计和回看提供了基础数据，但当前不包含 Web 查询界面。

---

## 13. 照片留存

从 v4.2 开始：

1. 告警时拍照并发送飞书
2. 学习开始时拍照并发送飞书
3. 学习结束时拍照并发送飞书
4. 照片路径记录在诊断日志的告警事件中

照片保存函数 `save_photo()` 直接保存 RGB 帧，不做多余颜色转换，避免颜色反转。
