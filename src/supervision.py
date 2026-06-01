"""
监督逻辑模块 v3.1 - 修复 StudySession
"""
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum


class AlertType(Enum):
    POSTURE_BAD = "posture_bad"
    TOO_CLOSE = "too_close"
    BREAK_NEEDED = "break_needed"
    BREAK_OVER = "break_over"


@dataclass
class Alert:
    alert_type: AlertType
    message: str
    timestamp: float
    details: Dict[str, Any] = field(default_factory=dict)


class SupervisionConfig:
    """监督配置"""
    # 距离
    too_close_threshold_cm: float = 35.0
    too_close_duration: float = 3.0  # 持续多久才提醒

    # 坐姿
    bad_posture_duration: float = 5.0  # 持续多久才提醒

    # 学习时长
    max_study_duration: float = 45 * 60  # 45分钟
    rest_duration: float = 10 * 60  # 10分钟

    # 提醒冷却（避免刷屏）
    alert_cooldown: float = 30.0


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
    """监督逻辑主类"""

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

    def on_person_detected(self, timestamp: float) -> Optional[Alert]:
        """检测到有人"""
        if self.is_resting:
            return None

        if self.current_session is None:
            # 新学习会话开始
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

        # 重置不良状态计时
        self.bad_posture_start = None
        self.too_close_start = None

        return None

    def on_posture_update(self, is_bad: bool, issues: list[str], timestamp: float) -> Optional[Alert]:
        """更新姿态状态"""
        if is_bad:
            if self.bad_posture_start is None:
                self.bad_posture_start = timestamp
            else:
                duration = timestamp - self.bad_posture_start
                if duration > self.config.bad_posture_duration:
                    if self._should_alert(AlertType.POSTURE_BAD, timestamp):
                        self._record_alert(AlertType.POSTURE_BAD)
                        return Alert(
                            alert_type=AlertType.POSTURE_BAD,
                            message=f"Bad Posture: {', '.join(issues)}",
                            timestamp=timestamp,
                            details={"duration": duration, "issues": issues},
                        )
        else:
            self.bad_posture_start = None

        return None

    def on_distance_update(self, distance_cm: Optional[float], timestamp: float) -> Optional[Alert]:
        """更新距离状态"""
        if distance_cm is not None and distance_cm < self.config.too_close_threshold_cm:
            if self.too_close_start is None:
                self.too_close_start = timestamp
            else:
                duration = timestamp - self.too_close_start
                if duration > self.config.too_close_duration:
                    if self._should_alert(AlertType.TOO_CLOSE, timestamp):
                        self._record_alert(AlertType.TOO_CLOSE)
                        return Alert(
                            alert_type=AlertType.TOO_CLOSE,
                            message=f"Too Close: {distance_cm:.1f}cm",
                            timestamp=timestamp,
                            details={"duration": duration, "distance": distance_cm},
                        )
        else:
            self.too_close_start = None

        return None

    def check_study_time(self, timestamp: float) -> Optional[Alert]:
        """检查学习时长，看是否需要休息"""
        if self.is_resting:
            if self.rest_start_time:
                rest_duration = timestamp - self.rest_start_time
                if rest_duration > self.config.rest_duration:
                    # 休息结束
                    self.is_resting = False
                    self.rest_start_time = None
                    return Alert(
                        alert_type=AlertType.BREAK_OVER,
                        message="Break Over!",
                        timestamp=timestamp,
                    )
        else:
            if self.current_session:
                study_duration = self.current_session.duration
                if study_duration > self.config.max_study_duration:
                    if self._should_alert(AlertType.BREAK_NEEDED, timestamp):
                        # 该休息了
                        self.is_resting = True
                        self.rest_start_time = timestamp
                        if self.current_session:
                            self.current_session.end_time = timestamp
                            self.current_session = None
                        return Alert(
                            alert_type=AlertType.BREAK_NEEDED,
                            message=f"Time to take a break! Studied for {study_duration/60:.1f} minutes",
                            timestamp=timestamp,
                            details={"study_duration": study_duration},
                        )

        return None

    def _should_alert(self, alert_type: AlertType, timestamp: float) -> bool:
        """检查是否在冷却期内"""
        last_time = self.last_alert_time.get(alert_type, 0)
        return timestamp - last_time > self.config.alert_cooldown

    def _record_alert(self, alert_type: AlertType):
        """记录提醒次数"""
        if self.current_session:
            if alert_type == AlertType.POSTURE_BAD:
                self.current_session.bad_posture_count += 1
            elif alert_type == AlertType.TOO_CLOSE:
                self.current_session.too_close_count += 1
