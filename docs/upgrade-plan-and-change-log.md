# 升级改造说明

## 1. 目标

本轮改造聚焦树莓派 5 单摄像头儿童学习监督场景，目标是：

1. 提升长期运行稳定性
2. 提升监督结果的可信度与可解释性
3. 按正面/侧面机位拆分检测策略
4. 保持实现轻量、可维护、可测试

本次不引入云端、多摄像头或重型模型方案。

---

## 2. 本轮已完成改动

### 2.1 配置体系

新增：

1. `config.yaml`
2. `src/config.py`

改进内容：

1. 主进程、摄像头进程、推理进程统一通过 `load_config()` 加载配置
2. 提供默认值，避免仓库缺省时直接崩溃
3. 增加配置校验，发现非法值时提前失败
4. 增加以下关键配置：
   - `pose.camera_view`
   - `process.restart_reset_after_s`
   - `supervision.presence_enter_frames`
   - `supervision.presence_exit_frames`
   - `supervision.distance_confidence_grace_s`
   - `storage.sqlite_path`
   - `notifier.*`

### 2.2 主进程稳定性

修改文件：`main.py`

改进内容：

1. 新增 `ProcessState`，统一管理子进程状态
2. 修复重启计数永久累积问题
3. 增加稳定运行一定时间后自动清零逻辑
4. 增加周期状态日志
5. 保留退避重启策略，但提高长期运行可恢复性

### 2.3 摄像头服务端

修改文件：`camera_server.py`

改进内容：

1. 对连接 socket 设置发送超时
2. 发送统计改为真实字节数
3. JPEG 编码失败时显式处理
4. 默认不再输出大量传感器模式调试信息

### 2.4 推理客户端主循环

修改文件：`inference_client.py`

改进内容：

1. 使用接收线程单独拉流
2. 主循环只消费最新帧，避免接收阻塞影响渲染、温控和退出响应
3. 引入统一运行统计：
   - 接收帧数
   - 推理帧数
   - 丢帧数
   - 解码失败数
   - 接收超时数
   - 重连次数
4. 温度改为优先读取 `/sys/class/thermal/thermal_zone0/temp`
5. 推理、显示、温控、状态日志的节拍彻底解耦
6. 收尾修复：socket 生命周期收口、优雅退出唤醒 receiver、丢帧统计去重

### 2.5 数据模型

修改文件：`src/vision/pose_detector.py`

`DetectionResult` 新增正式字段：

1. `frame_id`
2. `source_timestamp`
3. `issues`

这样避免了原先动态挂载 `_frame_id` 和动态拼接 `issues` 的脆弱写法。

### 2.6 监督状态机

修改文件：`src/supervision.py`

改进内容：

1. 修复告警冷却时间记录
2. `BREAK_NEEDED` 和 `BREAK_OVER` 也进入统一记录逻辑
3. 低置信度距离读数增加宽限期，不再立刻清空累计状态
4. 增加 `session_history`
5. 会话结束时保留历史摘要，避免数据直接丢失

### 2.7 告警输出

修改文件：`src/notifier.py`

改进内容：

1. 接入主链路
2. `Supervisor` 仅负责产出 `Alert`
3. `Notifier` 负责控制台输出和未来 TTS 扩展口
4. 告警标签改为 ASCII 风格，避免环境兼容问题

### 2.8 距离估算链路

修改文件：`src/vision/pose_detector.py`

改进内容：

1. 废弃“鼻子中心 + 固定尺寸方框”作为正式距离输入
2. 改为根据头部关键点估计真实脸框范围
3. 保留：
   - 边缘区域降权
   - 距离置信度分级
   - EMA 平滑
4. 距离提醒仅在 `front` 机位启用

说明：

这仍然是轻量级近似测距，但已经比固定方框方案更可信。

### 2.9 机位模式

修改文件：

1. `config.yaml`
2. `src/vision/pose_detector.py`
3. `src/supervision.py`

支持：

1. `front`
2. `side`

规则差异：

#### front

重点检测：

1. 距离过近
2. 低头
3. 歪头
4. 前倾
5. 双肩不平

#### side

重点检测：

1. 头前伸
2. 趴桌/贴桌趋势
3. 前倾

侧面模式下不再主打精确距离提醒。

### 2.10 预览渲染

修改文件：`src/preview_renderer.py`

改进内容：

1. 明确预览输入为 RGB 帧
2. 删除不必要的颜色来回转换
3. 显示阈值与监督阈值对齐
4. UI 只保留核心监督信息

### 2.11 最小持久化

新增：`src/storage.py`

改进内容：

1. 使用 SQLite 保存学习会话
2. 保存字段：
   - 开始时间
   - 结束时间
   - 时长
   - 坏姿态次数
   - 过近次数
   - 机位模式
3. 增加唯一索引与 upsert，避免重复写入相同会话

### 2.12 距离校准工具

修改文件：`calibrate_distance.py`

改进内容：

1. 复用正式检测器
2. 采样真实脸框宽度
3. 直接写回 `config.yaml`
4. 不再要求手工改源码

---

## 3. 关键文件清单

### 新增文件

1. `config.yaml`
2. `src/config.py`
3. `src/storage.py`
4. `docs/upgrade-plan-and-change-log.md`

### 主要重构文件

1. `main.py`
2. `camera_server.py`
3. `inference_client.py`
4. `src/vision/pose_detector.py`
5. `src/supervision.py`
6. `src/preview_renderer.py`
7. `src/notifier.py`
8. `calibrate_distance.py`

---

## 4. 当前推荐部署方式

### 4.1 正面机位

适合场景：

1. 摄像头在屏幕上方
2. 摄像头在桌前偏上方

优点：

1. 距离判断更可信
2. 低头和歪头更容易识别
3. 存在检测更稳定

配置：

```yaml
pose:
  camera_view: front
```

### 4.2 侧面机位

适合场景：

1. 摄像头在座位侧面
2. 更关心前倾、头前伸、趴桌

优点：

1. 前倾和头前伸更容易看出来
2. 更贴合“趴桌监督”

配置：

```yaml
pose:
  camera_view: side
```

说明：

侧面模式下不建议将“距离值”作为主要决策依据。

---

## 5. 关键配置建议

### 5.1 稳定性优先

```yaml
camera:
  width: 640
  height: 480
  fps: 20

inference:
  inference_fps: 10
  display_fps: 15

thermal:
  enabled: true
  temp_throttle_c: 75.0

process:
  max_restart_attempts: 3
  restart_reset_after_s: 60
```

### 5.2 正面机位默认

```yaml
pose:
  camera_view: front

supervision:
  too_close_threshold_cm: 30.0
  too_close_duration_s: 5.0
  bad_posture_duration_s: 8.0
```

### 5.3 侧面机位默认

```yaml
pose:
  camera_view: side
```

建议：

1. 侧面模式先观察 1-2 天，再调阈值
2. 不要一开始就把灵敏度调得太高

---

## 6. 校准流程

运行：

```bash
/usr/bin/python3 calibrate_distance.py
```

步骤：

1. 保持正面机位
2. 让孩子在已知距离处坐好
3. 稳定 2-3 秒
4. 按 `c`
5. 输入真实距离 cm
6. 工具自动写入 `config.yaml`

---

## 7. 已完成验证

执行：

```bash
python -m compileall main.py camera_server.py inference_client.py src calibrate_distance.py
```

结果：通过。

---

## 8. 后续建议

当前版本已经完成工程稳定性和核心业务收口。后续若继续提升，优先顺序建议为：

1. 更新 `README.md` 和原有 `docs/*.md`，使文档与现实现一致
2. 在树莓派实机分别测试 `front` / `side`
3. 观察实际误报情况后微调 `pose.weights` 与阈值
4. 若需要更高距离精度，再考虑引入轻量真实人脸检测框替换当前头部关键点估计
