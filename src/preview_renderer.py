"""
预览渲染器 v5.0 - 配置驱动，支持严重度显示
"""
import os
import cv2
import numpy as np
from typing import Optional, Any


class PreviewRenderer:
    """预览画面渲染器"""

    def __init__(self, enabled: bool = True, config: dict = None):
        self.enabled = enabled
        cfg = config or {}
        preview_cfg = cfg.get("preview", {})
        dist_cfg = cfg.get("distance", {})

        self.window_name = preview_cfg.get("window_name", "Kid Supervisor")
        self.distance_warn_cm = dist_cfg.get("min_cm", 30) + 5  # 略高于触发阈值

        # 检查显示器
        if self.enabled:
            try:
                if os.name != "nt":
                    display = os.environ.get("DISPLAY", "")
                    if not display:
                        print("[Preview] No display found, disabled")
                        self.enabled = False
            except Exception:
                pass

        # 颜色 (BGR)
        self.color_good = (0, 255, 0)
        self.color_bad = (0, 0, 255)
        self.color_warning = (0, 255, 255)
        self.color_info = (255, 255, 255)
        self.color_mild = (0, 200, 200)
        self.color_severe = (0, 0, 255)

    def should_render(self) -> bool:
        return self.enabled

    def render(
        self,
        frame: np.ndarray,
        detection_result: Any = None,
        supervisor_state: dict = None,
        alerts: list = None,
        pose=None,
        mp_drawing=None,
    ) -> np.ndarray:
        """渲染分析结果"""
        if not self.enabled or frame is None:
            return frame

        display_frame = frame.copy()
        h, w = display_frame.shape[:2]

        # 1. 画骨架
        if pose and mp_drawing and detection_result:
            landmarks = getattr(detection_result, "pose_landmarks", None)
            if landmarks:
                try:
                    mp_drawing.draw_landmarks(
                        display_frame,
                        landmarks,
                        pose.POSE_CONNECTIONS,
                        mp_drawing.DrawingSpec(color=(245, 117, 66), thickness=2, circle_radius=2),
                        mp_drawing.DrawingSpec(color=(245, 66, 230), thickness=2, circle_radius=2),
                    )
                except Exception:
                    pass

        # 2. 画人脸框
        if detection_result:
            face_box = getattr(detection_result, "face_bbox", None)
            if face_box and len(face_box) == 4:
                x, y, fw, fh = face_box
                cv2.rectangle(display_frame, (x, y), (x + fw, y + fh), self.color_good, 2)

            # 3. 距离 + 置信度
            dist = getattr(detection_result, "estimated_distance_cm", None)
            confidence = getattr(detection_result, "distance_confidence", None)
            if dist is not None:
                dist_text = f"Distance: {dist:.1f}cm"
                if dist < self.distance_warn_cm:
                    color = self.color_bad
                else:
                    color = self.color_good

                # 加置信度标记
                if confidence is not None:
                    conf_label = confidence.value.upper() if hasattr(confidence, 'value') else str(confidence)
                    if conf_label == "LOW":
                        dist_text += " [?]"
                        color = self.color_warning

                cv2.putText(display_frame, dist_text, (20, h - 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            # 4. 姿态问题
            issues = getattr(detection_result, "issues", [])
            if issues:
                y_pos = h - 100
                for issue in issues[:3]:
                    cv2.putText(display_frame, issue, (20, y_pos),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.color_bad, 2)
                    y_pos -= 25

            # 4.5 姿态评分
            pose_metrics = getattr(detection_result, "pose_metrics", None)
            if pose_metrics:
                score = pose_metrics.posture_score
                score_text = f"Posture: {score:.0f}/100"
                if score < 30:
                    color = self.color_good
                elif score < 60:
                    color = self.color_mild
                else:
                    color = self.color_bad
                cv2.putText(display_frame, score_text, (20, h - 180),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # 5. 状态信息
        if supervisor_state:
            current_session = supervisor_state.get("current_session")
            is_resting = supervisor_state.get("is_resting", False)

            y_offset = 30

            if is_resting:
                status_text = "Resting..."
                color = self.color_warning
            elif current_session:
                duration = getattr(current_session, "duration", 0)
                mins = int(duration // 60)
                secs = int(duration % 60)
                status_text = f"Learning: {mins}m{secs:02d}s"
                color = self.color_good
            else:
                status_text = "Waiting..."
                color = self.color_info

            cv2.putText(display_frame, status_text, (20, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            y_offset += 30

            if current_session:
                bad_count = getattr(current_session, "bad_posture_count", 0)
                close_count = getattr(current_session, "too_close_count", 0)
                stats_text = f"Bad: {bad_count} | Close: {close_count}"
                cv2.putText(display_frame, stats_text, (20, y_offset),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.color_info, 1)

        # 6. 提醒横幅（按严重度着色）
        if alerts and len(alerts) > 0:
            last_alert = alerts[-1]
            alert_msg = getattr(last_alert, "message", "")
            severity = getattr(last_alert, "severity", None)

            if alert_msg:
                overlay = display_frame.copy()
                if hasattr(severity, 'value'):
                    if severity.value == "severe":
                        banner_color = (0, 0, 200)
                    elif severity.value == "moderate":
                        banner_color = (0, 100, 200)
                    else:
                        banner_color = (0, 150, 150)
                else:
                    banner_color = (0, 0, 255)

                cv2.rectangle(overlay, (0, 0), (w, 60), banner_color, -1)
                cv2.addWeighted(overlay, 0.3, display_frame, 0.7, 0, display_frame)
                cv2.putText(display_frame, alert_msg, (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.color_info, 2)

        # 7. 退出提示
        help_text = "Q / ESC to exit"
        cv2.putText(display_frame, help_text, (w - 150, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, self.color_info, 1)

        return display_frame

    def show(self, frame: np.ndarray) -> bool:
        """显示画面"""
        if not self.enabled:
            return True

        if frame is not None:
            try:
                cv2.imshow(self.window_name, frame)
            except Exception:
                pass

        try:
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                return False
        except Exception:
            pass

        return True

    def close(self):
        """关闭窗口"""
        if self.enabled:
            try:
                cv2.destroyWindow(self.window_name)
                cv2.destroyAllWindows()
            except Exception:
                pass
