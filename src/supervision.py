"""Core supervision state machine."""

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from vision.pose_detector import DistanceConfidence


class AlertType(Enum):
    POSTURE_BAD = "posture_bad"
    TOO_CLOSE = "too_close"
    BREAK_NEEDED = "break_needed"
    BREAK_OVER = "break_over"


class AlertSeverity(Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


@dataclass
class Alert:
    alert_type: AlertType
    message: str
    timestamp: float
    severity: AlertSeverity = AlertSeverity.MODERATE
    details: Dict[str, Any] = field(default_factory=dict)


class SupervisionConfig:
    def __init__(self, config: dict = None):
        config = config or {}
        sup = config.get("supervision", {})
        pose = config.get("pose", {})
        self.camera_view: str = pose.get("camera_view", "front")
        self.too_close_threshold_cm: float = sup.get("too_close_threshold_cm", 30.0)
        self.too_close_duration: float = sup.get("too_close_duration_s", 5.0)
        self.distance_confidence_grace_s: float = sup.get("distance_confidence_grace_s", 1.5)
        self.bad_posture_duration: float = sup.get("bad_posture_duration_s", 8.0)
        self.max_study_duration: float = sup.get("max_study_duration_min", 45) * 60
        self.rest_duration: float = sup.get("rest_duration_min", 10) * 60
        self.alert_cooldown: float = sup.get("alert_cooldown_s", 45.0)
        self.posture_window_s: float = pose.get("posture_window_s", 4.0)
        self.posture_alert_threshold: float = pose.get("posture_alert_threshold", 60)
        self.severity_mild: float = sup.get("severity_mild_threshold", 30)
        self.severity_moderate: float = sup.get("severity_moderate_threshold", 60)
        self.severity_severe: float = sup.get("severity_severe_threshold", 80)
        self.presence_enter_frames: int = sup.get("presence_enter_frames", 2)
        self.presence_exit_frames: int = sup.get("presence_exit_frames", 5)


class StudySession:
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
    def __init__(self, config: SupervisionConfig = None):
        self.config = config or SupervisionConfig()
        self.current_session: Optional[StudySession] = None
        self.session_history: List[StudySession] = []
        self.is_resting: bool = False
        self.rest_start_time: Optional[float] = None
        self.bad_posture_start: Optional[float] = None
        self.too_close_start: Optional[float] = None
        self._distance_low_confidence_since: Optional[float] = None
        self.last_alert_time: Dict[AlertType, float] = {}
        self._posture_window: deque = deque()
        self._window_size_s = self.config.posture_window_s

    def _update_posture_window(self, timestamp: float, score: float):
        self._posture_window.append((timestamp, score))
        cutoff = timestamp - self._window_size_s
        while self._posture_window and self._posture_window[0][0] < cutoff:
            self._posture_window.popleft()

    def _get_window_avg_score(self) -> float:
        if not self._posture_window:
            return 0.0
        scores = [score for _, score in self._posture_window]
        return sum(scores) / len(scores)

    def _score_to_severity(self, score: float) -> AlertSeverity:
        if score >= self.config.severity_severe:
            return AlertSeverity.SEVERE
        if score >= self.config.severity_moderate:
            return AlertSeverity.MODERATE
        return AlertSeverity.MILD

    def on_person_detected(self, timestamp: float) -> Optional[Alert]:
        if self.is_resting:
            return None
        if self.current_session is None:
            self.current_session = StudySession()
            self.current_session.start_time = timestamp
            print(f"[Supervisor] 学习开始 @ {timestamp:.1f}")
        return None

    def on_person_left(self, timestamp: float) -> Optional[Alert]:
        if self.current_session is not None and not self.is_resting:
            self.current_session.end_time = timestamp
            print(f"[Supervisor] 学习暂停，持续了 {self.current_session.duration:.1f}s")
            self.session_history.append(self.current_session)
            self.current_session = None
        self.bad_posture_start = None
        self.too_close_start = None
        self._distance_low_confidence_since = None
        return None

    def on_posture_update(self, pose_metrics, timestamp: float) -> Optional[Alert]:
        self._update_posture_window(timestamp, pose_metrics.posture_score)
        avg_score = self._get_window_avg_score()
        if avg_score >= self.config.posture_alert_threshold:
            if self.bad_posture_start is None:
                self.bad_posture_start = timestamp
            else:
                duration = timestamp - self.bad_posture_start
                if duration > self.config.bad_posture_duration and self._should_alert(AlertType.POSTURE_BAD, timestamp):
                    severity = self._score_to_severity(avg_score)
                    self._record_alert(AlertType.POSTURE_BAD, timestamp)
                    issues = pose_metrics.issues if pose_metrics else []
                    return Alert(
                        alert_type=AlertType.POSTURE_BAD,
                        message=f"Bad Posture ({severity.value}): {', '.join(issues)}",
                        timestamp=timestamp,
                        severity=severity,
                        details={"duration": duration, "avg_score": avg_score, "issues": issues},
                    )
        else:
            self.bad_posture_start = None
        return None

    def on_distance_update(self, distance_cm: Optional[float], confidence=None, timestamp: float = 0) -> Optional[Alert]:
        if self.config.camera_view != "front":
            self.too_close_start = None
            self._distance_low_confidence_since = None
            return None

        if confidence == DistanceConfidence.LOW:
            if self._distance_low_confidence_since is None:
                self._distance_low_confidence_since = timestamp
            elif timestamp - self._distance_low_confidence_since > self.config.distance_confidence_grace_s:
                self.too_close_start = None
            return None

        self._distance_low_confidence_since = None
        if distance_cm is not None and distance_cm < self.config.too_close_threshold_cm:
            if self.too_close_start is None:
                self.too_close_start = timestamp
            else:
                duration = timestamp - self.too_close_start
                if duration > self.config.too_close_duration and self._should_alert(AlertType.TOO_CLOSE, timestamp):
                    severity = AlertSeverity.SEVERE if distance_cm < 20 else AlertSeverity.MODERATE
                    self._record_alert(AlertType.TOO_CLOSE, timestamp)
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
        if self.is_resting:
            if self.rest_start_time and timestamp - self.rest_start_time > self.config.rest_duration:
                self.is_resting = False
                self.rest_start_time = None
                self._record_alert(AlertType.BREAK_OVER, timestamp)
                return Alert(AlertType.BREAK_OVER, "Break Over!", timestamp, AlertSeverity.MILD)
        elif self.current_session and self.current_session.duration > self.config.max_study_duration:
            if self._should_alert(AlertType.BREAK_NEEDED, timestamp):
                self.is_resting = True
                self.rest_start_time = timestamp
                self.current_session.end_time = timestamp
                self.session_history.append(self.current_session)
                self.current_session = None
                self._record_alert(AlertType.BREAK_NEEDED, timestamp)
                return Alert(
                    AlertType.BREAK_NEEDED,
                    f"Time for a break! Studied {(self.session_history[-1].duration) / 60:.0f} min",
                    timestamp,
                    AlertSeverity.SEVERE,
                    {"study_duration": self.session_history[-1].duration},
                )
        return None

    def _should_alert(self, alert_type: AlertType, timestamp: float) -> bool:
        last_time = self.last_alert_time.get(alert_type, 0)
        return timestamp - last_time > self.config.alert_cooldown

    def _record_alert(self, alert_type: AlertType, timestamp: float):
        self.last_alert_time[alert_type] = timestamp
        if self.current_session:
            if alert_type == AlertType.POSTURE_BAD:
                self.current_session.bad_posture_count += 1
            elif alert_type == AlertType.TOO_CLOSE:
                self.current_session.too_close_count += 1
