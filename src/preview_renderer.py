"""Preview rendering for RGB frames."""

import os

import cv2
import numpy as np


class PreviewRenderer:
    def __init__(self, enabled: bool = True, config: dict = None):
        self.enabled = enabled
        cfg = config or {}
        preview_cfg = cfg.get("preview", {})
        supervision_cfg = cfg.get("supervision", {})
        self.window_name = preview_cfg.get("window_name", "Kid Supervisor")
        self.distance_warn_cm = supervision_cfg.get("too_close_threshold_cm", 30)
        self.show_help = preview_cfg.get("show_help", True)

        if self.enabled and os.name != "nt":
            display = os.environ.get("DISPLAY", "")
            if not display:
                print("[Preview] No display found, disabled")
                self.enabled = False

        self.color_good = (0, 255, 0)
        self.color_bad = (255, 0, 0)
        self.color_warning = (255, 255, 0)
        self.color_info = (255, 255, 255)
        self.color_mild = (0, 200, 200)

    def render(self, frame: np.ndarray, detection_result=None, supervisor_state=None, alerts=None, pose=None, mp_drawing=None) -> np.ndarray:
        if not self.enabled or frame is None:
            return frame

        display_frame = frame.copy()
        h, w = display_frame.shape[:2]

        if pose and mp_drawing and detection_result and getattr(detection_result, "pose_landmarks", None):
            try:
                mp_drawing.draw_landmarks(
                    display_frame,
                    detection_result.pose_landmarks,
                    pose.POSE_CONNECTIONS,
                    mp_drawing.DrawingSpec(color=(245, 117, 66), thickness=2, circle_radius=2),
                    mp_drawing.DrawingSpec(color=(245, 66, 230), thickness=2, circle_radius=2),
                )
            except Exception:
                pass

        if detection_result:
            face_box = getattr(detection_result, "face_bbox", None)
            if face_box and len(face_box) == 4:
                x, y, fw, fh = face_box
                cv2.rectangle(display_frame, (x, y), (x + fw, y + fh), self.color_good, 2)

            dist = getattr(detection_result, "estimated_distance_cm", None)
            confidence = getattr(detection_result, "distance_confidence", None)
            if dist is not None:
                color = self.color_bad if dist < self.distance_warn_cm else self.color_good
                dist_text = f"Distance: {dist:.1f}cm"
                if confidence is not None and getattr(confidence, "value", "") == "low":
                    dist_text += " [?]"
                    color = self.color_warning
                cv2.putText(display_frame, dist_text, (20, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            issues = getattr(detection_result, "issues", [])
            if issues:
                y_pos = h - 100
                for issue in issues[:3]:
                    cv2.putText(display_frame, issue, (20, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.color_bad, 2)
                    y_pos -= 25

            pose_metrics = getattr(detection_result, "pose_metrics", None)
            if pose_metrics:
                score = pose_metrics.posture_score
                color = self.color_good if score < 30 else self.color_mild if score < 60 else self.color_bad
                cv2.putText(display_frame, f"Posture: {score:.0f}/100", (20, h - 180), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        if supervisor_state:
            current_session = supervisor_state.get("current_session")
            is_resting = supervisor_state.get("is_resting", False)
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
            cv2.putText(display_frame, status_text, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            if current_session:
                cv2.putText(
                    display_frame,
                    f"Bad: {current_session.bad_posture_count} | Close: {current_session.too_close_count}",
                    (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    self.color_info,
                    1,
                )

        if alerts:
            last_alert = alerts[-1]
            alert_msg = getattr(last_alert, "message", "")
            severity = getattr(getattr(last_alert, "severity", None), "value", "moderate")
            banner_color = (180, 0, 0) if severity == "severe" else (180, 90, 0) if severity == "moderate" else (120, 120, 0)
            overlay = display_frame.copy()
            cv2.rectangle(overlay, (0, 0), (w, 60), banner_color, -1)
            cv2.addWeighted(overlay, 0.3, display_frame, 0.7, 0, display_frame)
            cv2.putText(display_frame, alert_msg, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.color_info, 2)

        if self.show_help:
            cv2.putText(display_frame, "Q / ESC to exit", (w - 150, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, self.color_info, 1)
        return display_frame

    def show(self, frame: np.ndarray) -> bool:
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
        if self.enabled:
            try:
                cv2.destroyWindow(self.window_name)
                cv2.destroyAllWindows()
            except Exception:
                pass
