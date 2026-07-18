"""Core supervision state machine."""

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from vision.pose_detector import DistanceConfidence
except Exception:
    class DistanceConfidence(Enum):
        HIGH = "high"
        MEDIUM = "medium"
        LOW = "low"


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
        dist = config.get("distance", {})
        self.camera_view: str = pose.get("camera_view", "front")
        self.too_close_threshold_cm: float = sup.get("too_close_threshold_cm", 30.0)
        self.too_close_severe_distance_margin_cm: float = sup.get("too_close_severe_distance_margin_cm", 5.0)
        self.too_close_severe_relative_multiplier: float = sup.get("too_close_severe_relative_multiplier", 1.25)
        self.baseline_face_width_px: float = dist.get("baseline_face_width_px", 0) or 0
        self.too_close_relative_scale: float = dist.get("too_close_relative_scale", 1.25)
        self.prefer_relative_baseline: bool = dist.get("prefer_relative_baseline", False)
        self.too_close_duration: float = sup.get("too_close_duration_s", 5.0)
        self.distance_recovery_s: float = sup.get("distance_recovery_s", 1.5)
        self.distance_confidence_grace_s: float = sup.get("distance_confidence_grace_s", 1.5)
        self.presence_grace_s: float = sup.get("presence_grace_s", 2.0)
        self.bad_posture_duration: float = sup.get("bad_posture_duration_s", 8.0)
        self.posture_recovery_s: float = sup.get("posture_recovery_s", 2.0)
        self.max_study_duration: float = sup.get("max_study_duration_min", 45) * 60
        self.rest_duration: float = sup.get("rest_duration_min", 10) * 60
        self.alert_cooldown: float = sup.get("alert_cooldown_s", 45.0)
        self.posture_window_s: float = pose.get("posture_window_s", 4.0)
        self.posture_alert_threshold: float = pose.get("posture_alert_threshold", 60)
        self.min_quality_score: float = pose.get("min_quality_score", 0.55)
        self.min_visible_keypoints: int = pose.get("min_visible_keypoints", 4)
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
        self._posture_recover_since: Optional[float] = None
        self._too_close_recover_since: Optional[float] = None
        self._distance_low_confidence_since: Optional[float] = None
        self.last_alert_time: Dict[AlertType, float] = {}
        self._posture_window: deque = deque()
        self._window_size_s = self.config.posture_window_s

    def _update_posture_window(self, timestamp: float, score: float):
        self._posture_window.append((timestamp, score))
        cutoff = timestamp - self._window_size_s
        while self._posture_window and self._posture_window[0][0] < cutoff:
            self._posture_window.popleft()

    def _clear_posture_window(self):
        self._posture_window.clear()

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
        self._posture_recover_since = None
        self._too_close_recover_since = None
        self._clear_posture_window()
        return None

    def on_posture_update(self, pose_metrics, timestamp: float) -> Optional[Alert]:
        quality_score = getattr(pose_metrics, "quality_score", 1.0)
        visible_keypoints = getattr(pose_metrics, "visible_keypoints", self.config.min_visible_keypoints)
        min_visible_keypoints = self.config.min_visible_keypoints
        if self.config.camera_view == "side":
            min_visible_keypoints = min(min_visible_keypoints, 3)
        if quality_score < self.config.min_quality_score or visible_keypoints < min_visible_keypoints:
            self.bad_posture_start = None
            self._posture_recover_since = None
            return None

        self._update_posture_window(timestamp, pose_metrics.posture_score)
        avg_score = self._get_window_avg_score()
        if avg_score >= self.config.posture_alert_threshold:
            self._posture_recover_since = None
            if self.bad_posture_start is None:
                self.bad_posture_start = timestamp
            else:
                duration = timestamp - self.bad_posture_start
                if duration > self.config.bad_posture_duration and self._should_alert(AlertType.POSTURE_BAD, timestamp):
                    severity = self._score_to_severity(avg_score)
                    self._record_alert(AlertType.POSTURE_BAD, timestamp)
                    issues = pose_metrics.issues if pose_metrics else []
                    issue_details = getattr(pose_metrics, "issue_details", {}) if pose_metrics else {}

                    # 找出得分最高的问题
                    main_issue = None
                    max_score = 0
                    for issue, detail in issue_details.items():
                        if detail.get("score", 0) > max_score:
                            max_score = detail.get("score", 0)
                            main_issue = issue

                    # 如果没找到但有 issues，取第一个
                    if not main_issue and issues:
                        main_issue = issues[0]

                    severity_translations = {
                        "mild": "轻度",
                        "moderate": "中度",
                        "severe": "重度",
                    }
                    severity_str = severity_translations.get(severity.value, severity.value)

                    # 构建告警消息 - 只报最严重的问题
                    if main_issue:
                        message = f"{main_issue} ({severity_str})"
                    else:
                        message = f"姿势异常 ({severity_str})"

                    return Alert(
                        alert_type=AlertType.POSTURE_BAD,
                        message=message,
                        timestamp=timestamp,
                        severity=severity,
                        details={
                            "duration": duration,
                            "avg_score": avg_score,
                            "issues": issues,
                            "issue_details": issue_details,
                            "main_issue": main_issue
                        },
                    )
        else:
            if self.bad_posture_start is not None:
                if self._posture_recover_since is None:
                    self._posture_recover_since = timestamp
                elif timestamp - self._posture_recover_since >= self.config.posture_recovery_s:
                    self.bad_posture_start = None
                    self._posture_recover_since = None
            else:
                self._posture_recover_since = None
        return None

    def on_distance_update(
        self,
        distance_cm: Optional[float],
        confidence=None,
        timestamp: float = 0,
        face_width_px: Optional[float] = None,
    ) -> Optional[Alert]:
        if self.config.camera_view != "front":
            self.too_close_start = None
            self._distance_low_confidence_since = None
            return None

        if confidence == DistanceConfidence.LOW:
            if self._distance_low_confidence_since is None:
                self._distance_low_confidence_since = timestamp
            elif timestamp - self._distance_low_confidence_since > self.config.distance_confidence_grace_s:
                self.too_close_start = None
                self._too_close_recover_since = None
            return None

        self._distance_low_confidence_since = None

        relative_scale = None
        if self.config.baseline_face_width_px > 0 and face_width_px is not None:
            relative_scale = face_width_px / self.config.baseline_face_width_px

        too_close_by_relative = (
            relative_scale is not None and relative_scale >= self.config.too_close_relative_scale
        )
        too_close_by_absolute = distance_cm is not None and distance_cm < self.config.too_close_threshold_cm
        if self.config.prefer_relative_baseline and relative_scale is not None:
            is_too_close = too_close_by_relative
        else:
            is_too_close = too_close_by_relative or too_close_by_absolute

        if is_too_close:
            self._too_close_recover_since = None
            if self.too_close_start is None:
                self.too_close_start = timestamp
            else:
                duration = timestamp - self.too_close_start
                if duration > self.config.too_close_duration and self._should_alert(AlertType.TOO_CLOSE, timestamp):
                    severe_by_absolute = distance_cm is not None and distance_cm <= (
                        self.config.too_close_threshold_cm - self.config.too_close_severe_distance_margin_cm
                    )
                    severe_by_relative = (
                        relative_scale is not None
                        and relative_scale >= self.config.too_close_relative_scale * self.config.too_close_severe_relative_multiplier
                    )
                    severity = AlertSeverity.SEVERE if (severe_by_absolute or severe_by_relative) else AlertSeverity.MODERATE
                    self._record_alert(AlertType.TOO_CLOSE, timestamp)
                    distance_text = f"{distance_cm:.1f}厘米" if distance_cm is not None else "相对距离"
                    if relative_scale is not None:
                        distance_text += f" / {relative_scale:.2f}倍基准"
                    severity_translations = {
                        "mild": "轻度",
                        "moderate": "中度",
                        "severe": "重度",
                    }
                    severity_str = severity_translations.get(severity.value, severity.value)
                    return Alert(
                        alert_type=AlertType.TOO_CLOSE,
                        message=f"距离太近 ({severity_str}): {distance_text}",
                        timestamp=timestamp,
                        severity=severity,
                        details={"duration": duration, "distance": distance_cm, "relative_scale": relative_scale},
                    )
        else:
            if self.too_close_start is not None:
                if self._too_close_recover_since is None:
                    self._too_close_recover_since = timestamp
                elif timestamp - self._too_close_recover_since >= self.config.distance_recovery_s:
                    self.too_close_start = None
                    self._too_close_recover_since = None
            else:
                self._too_close_recover_since = None
        return None

    def check_study_time(self, timestamp: float) -> Optional[Alert]:
        if self.is_resting:
            if self.rest_start_time and timestamp - self.rest_start_time > self.config.rest_duration:
                self.is_resting = False
                self.rest_start_time = None
                self._record_alert(AlertType.BREAK_OVER, timestamp)
                return Alert(AlertType.BREAK_OVER, "休息结束，可以继续学习了！", timestamp, AlertSeverity.MILD)
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
                    f"该休息了！已学习 {(self.session_history[-1].duration) / 60:.0f} 分钟",
                    timestamp,
                    AlertSeverity.SEVERE,
                    {"study_duration": self.session_history[-1].duration},
                )
        return None

    def _should_alert(self, alert_type: AlertType, timestamp: float) -> bool:
        last_time = self.last_alert_time.get(alert_type)
        if last_time is None:
            return True
        return timestamp - last_time > self.config.alert_cooldown

    def _record_alert(self, alert_type: AlertType, timestamp: float):
        self.last_alert_time[alert_type] = timestamp
        if self.current_session:
            if alert_type == AlertType.POSTURE_BAD:
                self.current_session.bad_posture_count += 1
            elif alert_type == AlertType.TOO_CLOSE:
                self.current_session.too_close_count += 1
