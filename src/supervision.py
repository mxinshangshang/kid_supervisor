"""
监督逻辑模块 v4.0
改进：滑动窗口姿态评分、严重度分级、距离置信度过滤、配置化
"""
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum


class AlertType(Enum):
    POSTURE_BAD = "posture_bad"
    TOO_CLOSE = "too_close"
    BREAK_NEEDED = "break_needed"
    BREAK_OVER = "break_over"


class AlertSeverity(Enum):
    MILD = "mild"           # 轻微提醒
    MODERATE = "moderate"   # 中等提醒
    SEVERE = "severe"       # 严重提醒


@dataclass
class Alert:
    alert_type: AlertType
    message: str
    timestamp: float
    severity: AlertSeverity = AlertSeverity.MODERATE
    details: Dict[str, Any] = field(default_factory=dict)


class SupervisionConfig:
    """监督配置 - 从 config.yaml 加载"""

    def __init__(self, config: dict = None):
        if config is None:
            config = {}

        sup = config.get("supervision", {})
        dist = config.get("distance", {})
        pose = config.get("pose", {})

        # 距离
        self.too_close_threshold_cm: float = sup.get("too_close_threshold_cm", 30.0)
        self.too_close_duration: float = sup.get("too_close_duration_s", 5.0)

        # 坐姿
        self.bad_posture_duration: float = sup.get("bad_posture_duration_s", 8.0)

        # 学习时长
        self.max_study_duration: float = sup.get("max_study_duration_min", 45) * 60
        self.rest_duration: float = sup.get("rest_duration_min", 10) * 60

        # 提醒冷却
        self.alert_cooldown: float = sup.get("alert_cooldown_s", 45.0)

        # 姿态评分滑动窗口
        self.posture_window_s: float = pose.get("posture_window_s", 4.0)
        self.posture_alert_threshold: float = pose.get("posture_alert_threshold", 60)

        # 严重度分级阈值
        self.severity_mild: float = sup.get("severity_mild_threshold", 30)
        self.severity_moderate: float = sup.get("severity_moderate_threshold", 60)
        self.severity_severe: float = sup.get("severity_severe_threshold", 80)


class StudySession:
    """学习会话记录"""

    def __init__(self):
        self.start_time: float = 0.0
        self.end_time: Optional[float] = None
        self.bad_posture_count: int = 0
        self.too_close_count: int = 0

    @property
    def duration(self) -> float:
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time


class Supervisor:
    """监督逻辑主类 - 带滑动窗口评分"""

    def __init__(self, config: SupervisionConfig = None):
        self.config = config or SupervisionConfig()

        # 状态
        self.current_session: Optional[StudySession] = None
        self.is_resting: bool = False
        self.rest_start_time: Optional[float] = None

        # 不良状态计时
        self.bad_posture_start: Optional[float] = None
        self.too_close_start: Optional[float] = None

        # 上次提醒时间
        self.last_alert_time: Dict[AlertType, float] = {}

        # 滑动窗口：姿态评分历史
        self._posture_window: deque = deque()  # (timestamp, score)
        self._window_size_s = self.config.posture_window_s

    def _update_posture_window(self, timestamp: float, score: float):
        """更新滑动窗口"""
        self._posture_window.append((timestamp, score))
        # 清理过期数据
        cutoff = timestamp - self._window_size_s
        while self._posture_window and self._posture_window[0][0] < cutoff:
            self._posture_window.popleft()

    def _get_window_avg_score(self) -> float:
        """获取滑动窗口内的平均姿态评分"""
        if not self._posture_window:
            return 0.0
        scores = [s for _, s in self._posture_window]
        return sum(scores) / len(scores)

    def _score_to_severity(self, score: float) -> AlertSeverity:
        """评分转严重度"""
        if score >= self.config.severity_severe:
            return AlertSeverity.SEVERE
        elif score >= self.config.severity_moderate:
            return AlertSeverity.MODERATE
        else:
            return AlertSeverity.MILD

    def on_person_detected(self, timestamp: float) -> Optional[Alert]:
        """检测到有人"""
        if self.is_resting:
            return None

        if self.current_session is None:
            self.current_session = StudySession()
            self.current_session.start_time = timestamp
            print(f"[Supervisor] 学习开始 @ {timestamp:.1f}")

        return None

    def on_person_left(self, timestamp: float) -> Optional[Alert]:
        """检测到人离开"""
        if self.current_session is not None and not self.is_resting:
            self.current_session.end_time = timestamp
            print(f"[Supervisor] 学习暂停，持续了 {self.current_session.duration:.1f}s")
            self.current_session = None

        self.bad_posture_start = None
        self.too_close_start = None
        return None

    def on_posture_update(self, pose_metrics, timestamp: float) -> Optional[Alert]:
        """更新姿态状态 - 使用滑动窗口评分"""
        score = pose_metrics.posture_score

        # 更新滑动窗口
        self._update_posture_window(timestamp, score)
        avg_score = self._get_window_avg_score()

        if avg_score >= self.config.posture_alert_threshold:
            if self.bad_posture_start is None:
                self.bad_posture_start = timestamp
            else:
                duration = timestamp - self.bad_posture_start
                if duration > self.config.bad_posture_duration:
                    if self._should_alert(AlertType.POSTURE_BAD, timestamp):
                        severity = self._score_to_severity(avg_score)
                        self._record_alert(AlertType.POSTURE_BAD)
                        issues = pose_metrics.issues if pose_metrics else []
                        return Alert(
                            alert_type=AlertType.POSTURE_BAD,
                            message=f"Bad Posture ({severity.value}): {', '.join(issues)}",
                            timestamp=timestamp,
                            severity=severity,
                            details={"duration": duration, "avg_score": avg_score,
                                      "issues": issues},
                        )
        else:
            self.bad_posture_start = None

        return None

    def on_distance_update(self, distance_cm: Optional[float], confidence=None,
                           timestamp: float = 0) -> Optional[Alert]:
        """更新距离状态 - 仅在置信度足够时触发提醒"""
        # 跳过低置信度的距离读数
        if confidence is not None:
            from vision.pose_detector import DistanceConfidence
            if confidence == DistanceConfidence.LOW:
                self.too_close_start = None
                return None

        if distance_cm is not None and distance_cm < self.config.too_close_threshold_cm:
            if self.too_close_start is None:
                self.too_close_start = timestamp
            else:
                duration = timestamp - self.too_close_start
                if duration > self.config.too_close_duration:
                    if self._should_alert(AlertType.TOO_CLOSE, timestamp):
                        severity = AlertSeverity.SEVERE if distance_cm < 20 else AlertSeverity.MODERATE
                        self._record_alert(AlertType.TOO_CLOSE)
                        return Alert(
                            alert_type=AlertType.TOO_CLOSE,
                            message=f"Too Close ({severity.value}): {distance_cm:.1f}cm",
                            timestamp=timestamp,
                            severity=severity,
                            details={"duration": duration, "distance": distance_cm},
                        )
        else:
            self.too_close_start = None

        return None

    def check_study_time(self, timestamp: float) -> Optional[Alert]:
        """检查学习时长"""
        if self.is_resting:
            if self.rest_start_time:
                rest_duration = timestamp - self.rest_start_time
                if rest_duration > self.config.rest_duration:
                    self.is_resting = False
                    self.rest_start_time = None
                    return Alert(
                        alert_type=AlertType.BREAK_OVER,
                        message="Break Over!",
                        timestamp=timestamp,
                        severity=AlertSeverity.MILD,
                    )
        else:
            if self.current_session:
                study_duration = self.current_session.duration
                if study_duration > self.config.max_study_duration:
                    if self._should_alert(AlertType.BREAK_NEEDED, timestamp):
                        self.is_resting = True
                        self.rest_start_time = timestamp
                        if self.current_session:
                            self.current_session.end_time = timestamp
                            self.current_session = None
                        return Alert(
                            alert_type=AlertType.BREAK_NEEDED,
                            message=f"Time for a break! Studied {study_duration/60:.0f} min",
                            timestamp=timestamp,
                            severity=AlertSeverity.SEVERE,
                            details={"study_duration": study_duration},
                        )

        return None

    def _should_alert(self, alert_type: AlertType, timestamp: float) -> bool:
        last_time = self.last_alert_time.get(alert_type, 0)
        return timestamp - last_time > self.config.alert_cooldown

    def _record_alert(self, alert_type: AlertType):
        if self.current_session:
            if alert_type == AlertType.POSTURE_BAD:
                self.current_session.bad_posture_count += 1
            elif alert_type == AlertType.TOO_CLOSE:
                self.current_session.too_close_count += 1
