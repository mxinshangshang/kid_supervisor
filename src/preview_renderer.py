"""Preview rendering for RGB frames."""

import os
import time

import cv2
import numpy as np


class PreviewRenderer:
    def __init__(self, enabled: bool = True, config: dict = None):
        self.enabled = enabled
        cfg = config or {}
        preview_cfg = cfg.get("preview", {})
        supervision_cfg = cfg.get("supervision", {})
        distance_cfg = cfg.get("distance", {})
        self.window_name = preview_cfg.get("window_name", "Kid Supervisor")
        self.distance_warn_cm = supervision_cfg.get("too_close_threshold_cm", 30)
        self.baseline_face_width_px = distance_cfg.get("baseline_face_width_px", 0) or 0
        self.too_close_relative_scale = distance_cfg.get("too_close_relative_scale", 1.25)
        self.prefer_relative_baseline = distance_cfg.get("prefer_relative_baseline", False)
        self.show_help = preview_cfg.get("show_help", True)
        self.show_debug_hud = preview_cfg.get("show_debug_hud", True)

        if self.enabled and os.name != "nt":
            display = os.environ.get("DISPLAY", "")
            if not display:
                print("[Preview] No display found, disabled")
                self.enabled = False

        # Colors are RGB. show() converts the final RGB frame to BGR for cv2.imshow.
        self.color_good = (0, 255, 0)
        self.color_bad = (255, 0, 0)
        self.color_warning = (255, 220, 0)
        self.color_info = (255, 255, 255)
        self.color_mild = (255, 180, 0)
        self.color_dim = (190, 190, 190)
        self.color_panel = (18, 18, 18)
        self.color_border = (95, 95, 95)

    def _distance_state(self, detection_result):
        dist = getattr(detection_result, "estimated_distance_cm", None)
        distance_box = getattr(detection_result, "distance_bbox", None)
        face_width_px = distance_box[2] if distance_box else None
        relative_scale = None
        if self.baseline_face_width_px > 0 and face_width_px is not None:
            relative_scale = face_width_px / self.baseline_face_width_px
        too_close_by_relative = relative_scale is not None and relative_scale >= self.too_close_relative_scale
        too_close_by_absolute = dist is not None and dist < self.distance_warn_cm
        if self.prefer_relative_baseline and relative_scale is not None:
            is_too_close = too_close_by_relative
        else:
            is_too_close = too_close_by_relative or too_close_by_absolute
        return dist, relative_scale, is_too_close

    def _measure_line(self, text, scale=0.45, thickness=1):
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        return tw, th

    def _draw_panel(self, frame, x, y, lines, accent_color):
        if not lines:
            return y

        pad_x = 12
        pad_y = 10
        line_gap = 8
        max_width = 0
        line_heights = []

        for text, _, scale, thickness in lines:
            tw, th = self._measure_line(text, scale, thickness)
            max_width = max(max_width, tw)
            line_heights.append(max(22, th + line_gap))

        panel_width = max_width + pad_x * 2
        panel_height = sum(line_heights) + pad_y * 2

        overlay = frame.copy()
        cv2.rectangle(overlay, (x, y), (x + panel_width, y + panel_height), self.color_panel, -1)
        cv2.rectangle(overlay, (x, y), (x + panel_width, y + panel_height), accent_color, 1)
        cv2.addWeighted(overlay, 0.58, frame, 0.42, 0, frame)

        text_y = y + pad_y + 2
        for idx, (text, color, scale, thickness) in enumerate(lines):
            _, th = self._measure_line(text, scale, thickness)
            text_y += max(22, th + line_gap) - 4
            cv2.putText(frame, text, (x + pad_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness)

        return y + panel_height

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

        dist = relative_scale = is_too_close = None
        pose_metrics = None
        confidence = None
        issues = []
        if detection_result:
            face_box = getattr(detection_result, "face_bbox", None)
            if face_box and len(face_box) == 4:
                x, y, fw, fh = face_box
                cv2.rectangle(display_frame, (x, y), (x + fw, y + fh), self.color_good, 2)

            pose_metrics = getattr(detection_result, "pose_metrics", None)
            dist, relative_scale, is_too_close = self._distance_state(detection_result)
            confidence = getattr(detection_result, "distance_confidence", None)
            issues = list(getattr(detection_result, "issues", [])[:2])

        left_lines = []
        right_lines = []

        if supervisor_state:
            current_session = supervisor_state.get("current_session")
            is_resting = supervisor_state.get("is_resting", False)
            if is_resting:
                status_text = "Resting"
                status_color = self.color_warning
            elif current_session:
                duration = getattr(current_session, "duration", 0)
                mins = int(duration // 60)
                secs = int(duration % 60)
                status_text = f"Learning {mins}m{secs:02d}s"
                status_color = self.color_good
            else:
                status_text = "Waiting"
                status_color = self.color_info

            left_lines.append((status_text, status_color, 0.62, 2))
            if current_session:
                left_lines.append((f"Bad {current_session.bad_posture_count} | Close {current_session.too_close_count}", self.color_dim, 0.45, 1))

        if alerts:
            last_alert = alerts[-1]
            alert_msg = getattr(last_alert, "message", "")
            severity = getattr(getattr(last_alert, "severity", None), "value", "moderate")
            alert_color = self.color_bad if severity == "severe" else self.color_mild if severity == "moderate" else self.color_warning
            left_lines.append((alert_msg[:36], alert_color, 0.45, 1))

        if pose_metrics:
            left_lines.append((f"Posture {pose_metrics.posture_score:.0f}/100", self.color_good if pose_metrics.posture_score < 30 else self.color_mild if pose_metrics.posture_score < 60 else self.color_bad, 0.5, 2))
            left_lines.append((f"Q {pose_metrics.quality_score:.2f} | KP {pose_metrics.visible_keypoints}", self.color_dim, 0.42, 1))

        if dist is not None:
            conf_label = getattr(confidence, "value", "?").upper() if confidence is not None else "?"
            dist_color = self.color_bad if is_too_close else self.color_good
            if conf_label == "LOW":
                dist_color = self.color_warning
            dist_text = f"Distance {dist:.1f}cm {conf_label}"
            if relative_scale is not None:
                dist_text += f" {relative_scale:.2f}x"
            left_lines.append((dist_text, dist_color, 0.5, 2))

        if issues:
            for issue in issues:
                left_lines.append((issue, self.color_bad, 0.42, 1))

        if self.show_debug_hud:
            conf_label = getattr(confidence, "value", "?").upper() if confidence is not None else "?"
            rel_text = f"REL {relative_scale:.2f}x" if relative_scale is not None else "REL -"
            right_lines.append((f"CONF {conf_label} | {rel_text}", self.color_dim, 0.42, 1))
            source_ts = getattr(detection_result, "source_timestamp", None) if detection_result else None
            if source_ts is not None:
                right_lines.append((f"AGE {max(0.0, time.time() - source_ts):.2f}s", self.color_dim, 0.42, 1))
            if supervisor_state:
                if "presence" in supervisor_state:
                    right_lines.append((supervisor_state["presence"], self.color_dim, 0.42, 1))
                if "runtime" in supervisor_state:
                    right_lines.append((supervisor_state["runtime"], self.color_dim, 0.42, 1))

        left_x = 12
        left_y = 12
        self._draw_panel(display_frame, left_x, left_y, left_lines[:6], self.color_border)

        if right_lines:
            right_width_est = max(self._measure_line(text, scale, thickness)[0] for text, _, scale, thickness in right_lines) + 20
            right_x = max(12, w - right_width_est - 12)
            right_y = 12
            self._draw_panel(display_frame, right_x, right_y, right_lines[:6], self.color_border)

        if self.show_help:
            help_text = "Q / ESC to exit"
            tw, th = self._measure_line(help_text, 0.38, 1)
            hx = max(12, w - tw - 20)
            hy = h - 12
            cv2.putText(display_frame, help_text, (hx, hy), cv2.FONT_HERSHEY_SIMPLEX, 0.38, self.color_dim, 1)

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
                # 处理一下事件队列，确保窗口完全关闭
                for _ in range(5):
                    cv2.waitKey(1)
            except Exception:
                pass
