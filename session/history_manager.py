"""历史记录管理器：保存和恢复项目启动历史。"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from launcher.environment_launcher import LaunchSession


# 历史记录存储路径
HISTORY_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "workbench"
HISTORY_FILE = HISTORY_DIR / "history.json"
MAX_HISTORY = 50  # 最多保留 50 条记录


@dataclass
class HistoryEntry:
    """一条历史记录。"""
    id: str
    project_name: str
    icon: str = "📁"
    color: str = "#4A90D9"
    started_at: float = 0.0
    items: list[dict] = field(default_factory=list)

    @property
    def formatted_time(self) -> str:
        """格式化时间显示。"""
        from datetime import datetime
        dt = datetime.fromtimestamp(self.started_at)
        now = datetime.now()
        if dt.date() == now.date():
            return f"今天 {dt.strftime('%H:%M')}"
        elif (now - dt).days == 1:
            return f"昨天 {dt.strftime('%H:%M')}"
        else:
            return dt.strftime("%m-%d %H:%M")

    @property
    def summary(self) -> str:
        """环境摘要（如 "VSCode + 终端 + Chrome"）。"""
        app_names = []
        for item in self.items:
            app = item.get("app", "")
            names = {
                "vscode": "VSCode",
                "obsidian": "Obsidian",
                "browser": "🌐",
                "terminal": ">_",
                "folder": "📂",
                "app": "App",
            }
            app_names.append(names.get(app, app))
        return " + ".join(app_names[:4]) if app_names else "无组件"


class HistoryManager:
    """历史记录管理器。"""

    def __init__(self):
        self._ensure_dir()

    def _ensure_dir(self):
        """确保历史目录存在。"""
        os.makedirs(HISTORY_DIR, exist_ok=True)

    def _load_all(self) -> list[dict]:
        """加载所有历史记录。"""
        if not HISTORY_FILE.exists():
            return []
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []

    def _save_all(self, entries: list[dict]):
        """保存所有历史记录。"""
        self._ensure_dir()
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    def save(self, session: LaunchSession, project_icon: str = "📁",
             project_color: str = "#4A90D9"):
        """保存一个会话到历史记录。

        Args:
            session: 启动会话。
            project_icon: 项目图标。
            project_color: 项目颜色。
        """
        entry = HistoryEntry(
            id=str(uuid.uuid4())[:8],
            project_name=session.project_name,
            icon=project_icon,
            color=project_color,
            started_at=session.started_at,
            items=[
                {
                    "app": r.env_item.app,
                    "target": r.env_item.target,
                    "command": r.env_item.command,
                    "browser": r.env_item.browser,
                    "args": r.env_item.args,
                }
                for r in session.results
            ],
        )

        entries = self._load_all()
        # 插入到最前面
        entries.insert(0, {
            "id": entry.id,
            "project_name": entry.project_name,
            "icon": entry.icon,
            "color": entry.color,
            "started_at": entry.started_at,
            "items": entry.items,
        })
        # 去重：相同 project_name 的旧记录只保留最新的
        seen = set()
        deduped = []
        for e in entries:
            key = e["project_name"]
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        # 限制数量
        deduped = deduped[:MAX_HISTORY]
        self._save_all(deduped)

    def get_recent(self, limit: int = 10) -> list[HistoryEntry]:
        """获取最近的若干条历史记录。

        Args:
            limit: 最多返回条数。

        Returns:
            HistoryEntry 列表。
        """
        entries = self._load_all()
        result = []
        for e in entries[:limit]:
            result.append(HistoryEntry(
                id=e.get("id", ""),
                project_name=e.get("project_name", ""),
                icon=e.get("icon", "📁"),
                color=e.get("color", "#4A90D9"),
                started_at=e.get("started_at", 0.0),
                items=e.get("items", []),
            ))
        return result

    def get_entry(self, entry_id: str) -> Optional[HistoryEntry]:
        """获取单条历史记录。

        Args:
            entry_id: 记录 ID。

        Returns:
            HistoryEntry 或 None。
        """
        entries = self._load_all()
        for e in entries:
            if e.get("id") == entry_id:
                return HistoryEntry(
                    id=e.get("id", ""),
                    project_name=e.get("project_name", ""),
                    icon=e.get("icon", "📁"),
                    color=e.get("color", "#4A90D9"),
                    started_at=e.get("started_at", 0.0),
                    items=e.get("items", []),
                )
        return None

    def delete(self, entry_id: str) -> bool:
        """删除一条历史记录。

        Args:
            entry_id: 记录 ID。

        Returns:
            是否成功删除。
        """
        entries = self._load_all()
        new_entries = [e for e in entries if e.get("id") != entry_id]
        if len(new_entries) < len(entries):
            self._save_all(new_entries)
            return True
        return False

    def clear_all(self):
        """清空所有历史记录。"""
        self._save_all([])
