"""会话管理器：管理当前活跃的项目环境，支持安全切换。

切换流程：
1. 对当前环境的 tracked_pids 调用 close_by_pids（WM_CLOSE）
2. 保存历史
3. 启动新环境（带 PID 快照差分追踪）
"""

from dataclasses import dataclass, field
from typing import Optional

from pathlib import Path

from config_loader import Project
from launcher.environment_launcher import EnvironmentLauncher, LaunchSession
from launcher.process_tracker import close_by_pids
from launcher.window_detector import focus_window, _extract_hostname
from session.history_manager import HistoryManager

def _build_title_rules(session: LaunchSession) -> list[dict]:
    """从会话结果构建标题匹配规则。"""
    rules = []
    for r in session.results:
        if not r.success:
            continue
        item = r.env_item
        if item.app == "vscode" and item.target:
            rules.append({
                "name": "code.exe",
                "title_kw": Path(item.target).name.lower(),
            })
        elif item.app == "obsidian" and item.target:
            rules.append({
                "name": "obsidian.exe",
                "title_kw": Path(item.target).name.lower(),
            })
        elif item.app == "terminal" and item.target:
            dir_name = Path(item.target).name.lower()
            for name in ("cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe"):
                rules.append({"name": name, "title_kw": f"▸工作台-{dir_name}"})
        elif item.app == "app" and item.target:
            # Electron 应用：优先用 title_kw，否则用 exe 文件名
            kw = item.title_kw.strip().lower() if item.title_kw else ""
            if not kw:
                kw = Path(item.target).stem.lower()
            if kw and len(kw) > 1:
                rules.append({"name": "", "title_kw": kw})
    return rules

def _close_browser_windows(session: LaunchSession) -> int:
    """关闭浏览器窗口（标题匹配 WM_CLOSE，不杀进程）。

    浏览器使用用户正常 Profile，taskkill 会杀掉主浏览器。
    改为枚举窗口标题 → 匹配 URL hostname → WM_CLOSE。
    """
    from urllib.parse import urlparse
    import win32gui, win32con

    # 收集所有浏览器 URL 的 hostname
    keywords: set[str] = set()
    for r in session.results:
        if r.success and r.env_item.app == "browser" and r.env_item.target:
            try:
                host = urlparse(r.env_item.target).hostname or ""
                if host:
                    keywords.add(host.lower())
                    # 简短域名（github.com → github）
                    short = host.split(".")[0]
                    if short != host and len(short) > 2:
                        keywords.add(short.lower())
            except Exception:
                pass

    if not keywords:
        return 0

    closed = 0
    for _ in range(3):  # 3 轮重试
        found = 0
        def callback(hwnd, _):
            nonlocal found
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                title = win32gui.GetWindowText(hwnd).lower()
                if any(kw in title for kw in keywords):
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    found += 1
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
        closed += found
        if found == 0:
            break
        import time
        time.sleep(0.8)

    return closed

@dataclass
class SwitchResult:
    closed_count: int = 0       # 成功关闭的进程数
    still_alive: int = 0        # 仍未退出的进程数
    close_details: list = field(default_factory=list)
    new_session: Optional[LaunchSession] = None
    message: str = ""

class SessionManager:

    def __init__(self, launcher: EnvironmentLauncher, history: HistoryManager):
        self.launcher = launcher
        self.history = history
        self.active_session: Optional[LaunchSession] = None
        self.active_project_name: str = ""

    def switch_to(self, project: Project) -> SwitchResult:
        result = SwitchResult()

        # === 同项目聚焦 ===
        if self.active_project_name == project.name and self.active_session:
            # 不关闭已有环境，只尝试聚焦窗口
            if self.active_session.tracked_pids:
                from launcher.process_tracker import get_process_info, _find_windows_for_pid
                for pid in self.active_session.tracked_pids:
                    try:
                        titles = _find_windows_for_pid(pid)
                        if titles:
                            # 用 window_detector 的 focus 逻辑
                            pass
                    except Exception:
                        pass
            result.message = f"已聚焦到「{project.name}」"
            result.new_session = self.active_session
            return result

        # === 关闭当前环境 ===
        if self.active_session:
            # 1. 先杀浏览器进程（独立 Profile，taskkill 直接杀）
            browser_killed = _close_browser_windows(self.active_session)

            # 2. 合并 PID：快照差分 + 启动时记录的直接 PID（如 app 类型）
            pids = list(self.active_session.tracked_pids)
            for r in self.active_session.results:
                if r.pid and r.pid not in pids:
                    pids.append(r.pid)
            title_rules = _build_title_rules(self.active_session)
            closed, alive, details = close_by_pids(pids, title_rules)

            result.closed_count = closed + browser_killed
            result.still_alive = alive
            result.close_details = details

            self.history.save(self.active_session)

        # === 启动新环境（含 PID 快照差分追踪） ===
        new_session = self.launcher.launch_environment(project)
        self.active_session = new_session
        self.active_project_name = project.name
        self.history.save(new_session, project.icon, project.color)

        # 构建消息
        parts = [f"已切换到「{project.name}」"]
        if result.closed_count > 0:
            parts.append(f"关闭了 {result.closed_count} 个进程")
        if result.still_alive > 0:
            parts.append(f"{result.still_alive} 个进程未完全退出")
        parts.append(f"启动了 {new_session.success_count} 个组件")
        parts.append(f"追踪到 {len(new_session.tracked_pids)} 个 PID")

        result.message = "；".join(parts)
        result.new_session = new_session
        return result

    def close_current(self) -> SwitchResult:
        result = SwitchResult()

        if not self.active_session:
            result.message = "没有正在运行的环境"
            return result

        if self.active_session:
            browser_killed = _close_browser_windows(self.active_session)
            pids = list(self.active_session.tracked_pids)
            for r in self.active_session.results:
                if r.pid and r.pid not in pids:
                    pids.append(r.pid)
            title_rules = _build_title_rules(self.active_session)
            closed, alive, details = close_by_pids(pids, title_rules)
            result.closed_count = closed + browser_killed
            result.still_alive = alive
            result.close_details = details

        self.history.save(self.active_session)
        self.active_session = None
        self.active_project_name = ""

        parts = [f"已关闭 {result.closed_count} 个进程"]
        if result.still_alive > 0:
            parts.append(f"{result.still_alive} 个进程未完全退出")
        result.message = "；".join(parts)
        return result

    def restore_history(self, entry) -> SwitchResult:
        if self.active_session:
            self.close_current()

        from config_loader import EnvItem
        env_items = []
        for item_data in entry.items:
            env_items.append(EnvItem(
                app=item_data.get("app", ""),
                target=item_data.get("target", ""),
                command=item_data.get("command", ""),
                browser=item_data.get("browser", "default"),
                args=item_data.get("args", ""),
            ))

        temp_project = Project(
            name=entry.project_name,
            icon=entry.icon,
            color=entry.color,
            environment=env_items,
        )

        new_session = self.launcher.launch_environment(temp_project)
        self.active_session = new_session
        self.active_project_name = entry.project_name
        self.history.save(new_session, entry.icon, entry.color)

        return SwitchResult(
            new_session=new_session,
            message=f"已恢复「{entry.project_name}」({new_session.success_count} 个组件)",
        )