"""
Diagnostic logger for algorithm computation results.
用于记录算法计算结果的维测日志，方便异常回溯排查。
自动清理规则：最多保留3天的日志。
"""

import os
import time
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any


class DiagnosticLogger:
    def __init__(self, db_path: str, retention_days: int = 3):
        """
        初始化维测日志记录器

        Args:
            db_path: SQLite数据库文件路径
            retention_days: 日志保留天数，默认3天
        """
        self.db_path = db_path
        self.retention_days = retention_days
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_db()
        # 上次清理时间
        self._last_cleanup_time = 0.0
        self._cleanup_interval = 3600.0  # 每小时检查一次清理

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=5.0)

    def _init_db(self):
        """初始化数据库表"""
        with self._connect() as conn:
            # 主维测日志表 - 记录每一帧的完整算法结果
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS diagnostic_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    frame_id INTEGER,
                    log_type TEXT NOT NULL,
                    data_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # 索引 - 按时间和类型查询
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_diag_logs_timestamp
                ON diagnostic_logs (timestamp)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_diag_logs_type
                ON diagnostic_logs (log_type)
                """
            )

            # 告警事件详细日志表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    alert_type TEXT NOT NULL,
                    severity TEXT,
                    message TEXT,
                    details_json TEXT,
                    photo_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_alert_events_timestamp
                ON alert_events (timestamp)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_alert_events_type
                ON alert_events (alert_type)
                """
            )

            # 学习会话状态变化日志
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    details_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_session_events_timestamp
                ON session_events (timestamp)
                """
            )

    def _cleanup_old_data_if_needed(self):
        """如果需要，清理过期数据"""
        now = time.time()
        if now - self._last_cleanup_time < self._cleanup_interval:
            return
        self._last_cleanup_time = now

        cutoff_time = now - (self.retention_days * 86400.0)

        try:
            with self._connect() as conn:
                # 清理维测日志
                deleted_logs = conn.execute(
                    "DELETE FROM diagnostic_logs WHERE timestamp < ?",
                    (cutoff_time,)
                ).rowcount

                # 清理告警事件
                deleted_alerts = conn.execute(
                    "DELETE FROM alert_events WHERE timestamp < ?",
                    (cutoff_time,)
                ).rowcount

                # 清理会话事件
                deleted_sessions = conn.execute(
                    "DELETE FROM session_events WHERE timestamp < ?",
                    (cutoff_time,)
                ).rowcount

                if deleted_logs > 0 or deleted_alerts > 0 or deleted_sessions > 0:
                    cutoff_str = datetime.fromtimestamp(cutoff_time).strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[DiagnosticLog] Cleaned up old data before {cutoff_str}: "
                          f"{deleted_logs} logs, {deleted_alerts} alerts, {deleted_sessions} session events")
        except Exception as e:
            print(f"[DiagnosticLog] Cleanup failed: {e}")

    def _safe_json_dumps(self, data: Any) -> Optional[str]:
        """安全地将数据转换为JSON"""
        if data is None:
            return None
        try:
            # 处理无法序列化的对象
            def default_converter(obj):
                if hasattr(obj, "__dict__"):
                    return obj.__dict__
                if hasattr(obj, "__str__"):
                    return str(obj)
                return repr(obj)

            return json.dumps(data, default=default_converter, ensure_ascii=False)
        except Exception:
            try:
                return json.dumps({"_raw": str(data)}, ensure_ascii=False)
            except Exception:
                return None

    def log_frame_result(self,
                        timestamp: float,
                        frame_id: Optional[int] = None,
                        detection_result: Any = None,
                        pose_metrics: Any = None,
                        distance_data: Dict[str, Any] = None,
                        supervisor_state: Dict[str, Any] = None):
        """
        记录一帧的完整算法计算结果

        Args:
            timestamp: 时间戳
            frame_id: 帧ID
            detection_result: 检测结果对象
            pose_metrics: 姿势 metrics
            distance_data: 距离数据
            supervisor_state: 监督器状态
        """
        self._cleanup_old_data_if_needed()

        data = {}
        if detection_result is not None:
            # 提取检测结果中的关键字段
            data["detection"] = {
                "success": getattr(detection_result, "success", False),
                "face_detected": getattr(detection_result, "face_bbox", None) is not None,
                "pose_detected": getattr(detection_result, "pose_landmarks", None) is not None,
            }
            if hasattr(detection_result, "face_bbox") and detection_result.face_bbox:
                data["detection"]["face_bbox"] = list(detection_result.face_bbox)
            if hasattr(detection_result, "distance_bbox") and detection_result.distance_bbox:
                data["detection"]["distance_bbox"] = list(detection_result.distance_bbox)
            if hasattr(detection_result, "estimated_distance_cm"):
                data["detection"]["distance_cm"] = detection_result.estimated_distance_cm
            if hasattr(detection_result, "distance_confidence"):
                data["detection"]["distance_confidence"] = getattr(
                    detection_result.distance_confidence, "value",
                    str(detection_result.distance_confidence)
                )

        if pose_metrics is not None:
            data["pose_metrics"] = {
                "posture_score": getattr(pose_metrics, "posture_score", None),
                "quality_score": getattr(pose_metrics, "quality_score", None),
                "visible_keypoints": getattr(pose_metrics, "visible_keypoints", None),
                "head_pitch": getattr(pose_metrics, "head_pitch", None),
                "head_roll": getattr(pose_metrics, "head_roll", None),
                "torso_lean": getattr(pose_metrics, "torso_lean", None),
                "shoulder_level": getattr(pose_metrics, "shoulder_level", None),
                "overall_quality": getattr(getattr(pose_metrics, "overall_quality", None), "value", None),
                "issues": list(getattr(pose_metrics, "issues", [])),
                "issue_details": getattr(pose_metrics, "issue_details", {}),
            }

        if distance_data is not None:
            data["distance"] = distance_data

        if supervisor_state is not None:
            data["supervisor"] = {
                "person_detected": supervisor_state.get("presence", "").startswith("P:True"),
                "current_session": supervisor_state.get("current_session") is not None,
                "is_resting": supervisor_state.get("is_resting", False),
            }

        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO diagnostic_logs
                    (timestamp, frame_id, log_type, data_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        timestamp,
                        frame_id,
                        "frame_result",
                        self._safe_json_dumps(data)
                    )
                )
        except Exception as e:
            print(f"[DiagnosticLog] Failed to log frame result: {e}")

    def log_alert_event(self,
                       timestamp: float,
                       alert_type: str,
                       severity: str,
                       message: str,
                       details: Any = None,
                       photo_path: Optional[str] = None):
        """
        记录告警事件

        Args:
            timestamp: 时间戳
            alert_type: 告警类型
            severity: 严重程度
            message: 告警消息
            details: 详细信息
            photo_path: 照片路径
        """
        self._cleanup_old_data_if_needed()

        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO alert_events
                    (timestamp, alert_type, severity, message, details_json, photo_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp,
                        alert_type,
                        severity,
                        message,
                        self._safe_json_dumps(details),
                        photo_path
                    )
                )
        except Exception as e:
            print(f"[DiagnosticLog] Failed to log alert event: {e}")

    def log_session_event(self,
                         timestamp: float,
                         event_type: str,
                         details: Any = None):
        """
        记录学习会话状态变化事件

        Args:
            timestamp: 时间戳
            event_type: 事件类型 ('start', 'end', 'pause', 'resume', 'rest_start', 'rest_end')
            details: 详细信息
        """
        self._cleanup_old_data_if_needed()

        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO session_events
                    (timestamp, event_type, details_json)
                    VALUES (?, ?, ?)
                    """,
                    (
                        timestamp,
                        event_type,
                        self._safe_json_dumps(details)
                    )
                )
        except Exception as e:
            print(f"[DiagnosticLog] Failed to log session event: {e}")

    def query_logs(self,
                  start_time: Optional[float] = None,
                  end_time: Optional[float] = None,
                  log_type: Optional[str] = None,
                  limit: int = 100) -> list:
        """查询维测日志"""
        query = "SELECT id, timestamp, frame_id, log_type, data_json FROM diagnostic_logs WHERE 1=1"
        params = []

        if start_time is not None:
            query += " AND timestamp >= ?"
            params.append(start_time)

        if end_time is not None:
            query += " AND timestamp <= ?"
            params.append(end_time)

        if log_type is not None:
            query += " AND log_type = ?"
            params.append(log_type)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        results = []
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                for row in conn.execute(query, params):
                    data = dict(row)
                    if data["data_json"]:
                        try:
                            data["data"] = json.loads(data["data_json"])
                        except Exception:
                            data["data"] = None
                    del data["data_json"]
                    results.append(data)
        except Exception as e:
            print(f"[DiagnosticLog] Query failed: {e}")

        return results

    def query_alerts(self,
                    start_time: Optional[float] = None,
                    end_time: Optional[float] = None,
                    alert_type: Optional[str] = None,
                    limit: int = 100) -> list:
        """查询告警事件"""
        query = "SELECT * FROM alert_events WHERE 1=1"
        params = []

        if start_time is not None:
            query += " AND timestamp >= ?"
            params.append(start_time)

        if end_time is not None:
            query += " AND timestamp <= ?"
            params.append(end_time)

        if alert_type is not None:
            query += " AND alert_type = ?"
            params.append(alert_type)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        results = []
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                for row in conn.execute(query, params):
                    data = dict(row)
                    if data["details_json"]:
                        try:
                            data["details"] = json.loads(data["details_json"])
                        except Exception:
                            data["details"] = None
                    del data["details_json"]
                    results.append(data)
        except Exception as e:
            print(f"[DiagnosticLog] Query alerts failed: {e}")

        return results

    def force_cleanup(self):
        """强制立即清理过期数据"""
        self._last_cleanup_time = 0.0
        self._cleanup_old_data_if_needed()

