"""FastAPI 路由：提供项目管理、环境切换、历史记录的 REST API。"""

import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from config_loader import (
    load_config,
    get_mod_time,
    Project,
    EnvItem,
    Config,
)
from launcher.environment_launcher import EnvironmentLauncher
from launcher.window_detector import (
    is_vscode_folder_open,
    is_obsidian_vault_open,
    is_browser_url_open,
)
from session.session_manager import SessionManager
from session.history_manager import HistoryManager

# ---- 全局状态 ----
_config: Config | None = None
_config_mtime: float = 0.0
_launcher: EnvironmentLauncher | None = None
_session_manager: SessionManager | None = None
_history_manager: HistoryManager | None = None


def _get_config() -> Config:
    """获取当前配置（支持热重载）。"""
    global _config, _config_mtime
    try:
        mtime = get_mod_time()
        if _config is None or mtime > _config_mtime:
            _config = load_config()
            _config_mtime = mtime
            # 更新 launcher 的 settings
            global _launcher
            if _launcher:
                _launcher.settings = _config.settings
    except Exception as e:
        if _config is None:
            raise HTTPException(status_code=500, detail=f"配置加载失败: {e}")
    return _config


def _get_launcher() -> EnvironmentLauncher:
    global _launcher, _launcher_config_version
    if _launcher is None:
        config = _get_config()
        _launcher = EnvironmentLauncher(config.settings)
    return _launcher


def _get_history() -> HistoryManager:
    global _history_manager
    if _history_manager is None:
        _history_manager = HistoryManager()
    return _history_manager


def _get_session() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager(_get_launcher(), _get_history())
    return _session_manager


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    app = FastAPI(title="工作台 Workbench", version="1.0.0")

    # ---- 静态文件 ----
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ========================================
    # API 路由
    # ========================================

    @app.get("/api/projects")
    async def get_projects():
        """获取所有项目配置。"""
        config = _get_config()
        projects_data = []
        for proj in config.projects:
            env_data = []
            for item in proj.environment:
                env_data.append({
                    "app": item.app,
                    "target": item.target,
                    "command": item.command,
                    "browser": item.browser,
                    "args": item.args,
                })
            projects_data.append({
                "name": proj.name,
                "icon": proj.icon,
                "color": proj.color,
                "category": proj.category,
                "environment": env_data,
            })
        return {
            "projects": projects_data,
            "settings": {
                "theme": config.settings.theme,
                "columns": config.settings.columns,
                "window_width": config.settings.window_width,
                "window_height": config.settings.window_height,
            }
        }

    @app.post("/api/switch/{project_name}")
    async def switch_project(project_name: str):
        """切换到指定项目环境。

        会先安全关闭当前环境，然后启动新环境。
        """
        config = _get_config()

        # 查找项目
        project = None
        for p in config.projects:
            if p.name == project_name:
                project = p
                break

        if project is None:
            raise HTTPException(status_code=404, detail=f"项目不存在: {project_name}")

        session = _get_session()
        result = session.switch_to(project)

        return {
            "success": True,
            "message": result.message,
            "closed_count": result.closed_count,
            "still_alive": result.still_alive,
            "close_details": result.close_details,
            "new_session": result.new_session.to_dict() if result.new_session else None,
        }

    @app.get("/api/status")
    async def get_status():
        """获取当前运行状态，含实时进程/窗口信息。"""
        from launcher.process_tracker import get_all_tracked_info
        session_mgr = _get_session()
        session = session_mgr.active_session

        if session is None:
            return {
                "active": False,
                "project_name": "",
                "tracked_pids": [],
                "processes": [],
                "started_at": 0,
                "items": [],
            }

        items = []
        for r in session.results:
            items.append({
                "app": r.env_item.app,
                "target": r.env_item.target,
                "success": r.success,
                "already_open": r.already_open,
                "error": r.error,
            })

        processes = get_all_tracked_info(session.tracked_pids)

        return {
            "active": True,
            "project_name": session.project_name,
            "tracked_pids": session.tracked_pids,
            "processes": processes,
            "started_at": session.started_at,
            "items": items,
            "success_count": session.success_count,
        }

    @app.post("/api/close-current")
    async def close_current():
        """关闭当前环境（不启动新的）。"""
        session = _get_session()
        result = session.close_current()
        return {
            "success": True,
            "message": result.message,
            "closed_count": result.closed_count,
            "still_alive": result.still_alive,
            "close_details": result.close_details,
        }

    @app.get("/api/history")
    async def get_history(limit: int = 10):
        """获取历史记录列表。"""
        history = _get_history()
        entries = history.get_recent(limit=limit)
        return {
            "history": [
                {
                    "id": e.id,
                    "project_name": e.project_name,
                    "icon": e.icon,
                    "color": e.color,
                    "started_at": e.started_at,
                    "formatted_time": e.formatted_time,
                    "summary": e.summary,
                    "items": e.items,
                }
                for e in entries
            ]
        }

    @app.post("/api/history/{entry_id}/restore")
    async def restore_history(entry_id: str):
        """一键恢复历史会话。"""
        history = _get_history()
        entry = history.get_entry(entry_id)

        if entry is None:
            raise HTTPException(status_code=404, detail=f"历史记录不存在: {entry_id}")

        session = _get_session()
        result = session.restore_history(entry)

        return {
            "success": True,
            "message": result.message,
            "new_session": result.new_session.to_dict() if result.new_session else None,
        }

    @app.delete("/api/history/{entry_id}")
    async def delete_history(entry_id: str):
        """删除一条历史记录。"""
        history = _get_history()
        ok = history.delete(entry_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"历史记录不存在: {entry_id}")
        return {"success": True}

    @app.delete("/api/history")
    async def clear_history():
        """清空所有历史记录。"""
        _get_history().clear_all()
        return {"success": True}

    @app.post("/api/detect")
    async def detect_project(data: dict):
        """检测某个项目是否已打开（去重检测）。"""
        project_name = data.get("project_name", "")
        config = _get_config()

        project = None
        for p in config.projects:
            if p.name == project_name:
                project = p
                break

        if project is None:
            raise HTTPException(status_code=404, detail=f"项目不存在: {project_name}")

        results = []
        for item in project.environment:
            info = {"app": item.app, "target": item.target, "already_open": False}
            if item.app == "vscode":
                already, _ = is_vscode_folder_open(item.target)
                info["already_open"] = already
            elif item.app == "obsidian":
                already, _ = is_obsidian_vault_open(item.target)
                info["already_open"] = already
            elif item.app == "browser":
                already, _ = is_browser_url_open(item.target, item.browser)
                info["already_open"] = already
            results.append(info)

        return {
            "project_name": project_name,
            "all_open": all(r["already_open"] for r in results) if results else False,
            "items": results,
        }

    @app.post("/api/reload")
    async def reload_config():
        """重新加载配置文件。"""
        global _config, _config_mtime
        try:
            _config = load_config()
            _config_mtime = get_mod_time()
            if _launcher:
                _launcher.settings = _config.settings
            return {"success": True, "message": "配置已重新加载"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"重新加载失败: {e}")

    @app.get("/")
    async def root():
        """主页：返回前端 HTML。"""
        from fastapi.responses import FileResponse
        index_path = Path(__file__).parent / "static" / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return JSONResponse(
            {"message": "工作台 API 已就绪", "docs": "/docs"},
            status_code=200,
        )

    return app
