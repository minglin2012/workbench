"""环境启动器 + 进程追踪。

核心流程：
1. 启动前：快照当前所有 PID
2. 逐一启动环境中的每个组件
3. 等待 1.5s 让进程产生
4. 快照差分 → 获得新 PID → 存入 Session
5. 关闭时按 PID 查窗口 → WM_CLOSE → 验证退出
"""

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .app_paths import find_browser, find_vscode, find_obsidian, find_terminal
from .window_detector import (
    is_vscode_folder_open,
    is_obsidian_vault_open,
    focus_window,
)
from .process_tracker import (
    _snapshot_pids,
    capture_new_processes,
    get_all_tracked_info,
    close_by_pids,
)
from config_loader import EnvItem, Settings

def _find_vault_id(vault_path: str) -> str:
    """从 Obsidian 的 obsidian.json 中查找匹配路径的 vault ID。

    obsidian.json 格式: {"vaults": {"<id>": {"path": "D:/..."}, ...}}
    返回 vault ID（16 位 hex），未找到返回空字符串。
    """
    import json
    appdata = os.environ.get("APPDATA", "")
    config_path = Path(appdata) / "Obsidian" / "obsidian.json"
    if not config_path.exists():
        return ""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        vaults = data.get("vaults", {})
        target = str(Path(vault_path).resolve()).replace("\\", "/").lower()
        for vid, info in vaults.items():
            registered = str(info.get("path", "")).replace("\\", "/").lower()
            if registered == target:
                return vid
    except Exception:
        pass
    return ""

# ---- 数据类 ----

@dataclass
class LaunchResult:
    env_item: EnvItem
    success: bool
    already_open: bool = False
    pid: Optional[int] = None
    error: str = ""

@dataclass
class LaunchSession:
    project_name: str
    results: list[LaunchResult] = field(default_factory=list)
    tracked_pids: list[int] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)

    def to_dict(self) -> dict:
        items = []
        for r in self.results:
            items.append({
                "app": r.env_item.app,
                "target": r.env_item.target,
                "command": r.env_item.command,
                "browser": r.env_item.browser,
                "success": r.success,
                "pid": r.pid,
                "already_open": r.already_open,
                "error": r.error,
            })
        return {
            "project_name": self.project_name,
            "started_at": self.started_at,
            "tracked_pids": self.tracked_pids,
            "items": items,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LaunchSession":
        session = cls(
            project_name=data.get("project_name", ""),
            started_at=data.get("started_at", time.time()),
            tracked_pids=data.get("tracked_pids", []),
        )
        for item_data in data.get("items", []):
            env_item = EnvItem(
                app=item_data.get("app", ""),
                target=item_data.get("target", ""),
                command=item_data.get("command", ""),
                browser=item_data.get("browser", "default"),
                args=item_data.get("args", ""),
            )
            session.results.append(LaunchResult(
                env_item=env_item,
                success=item_data.get("success", True),
                pid=item_data.get("pid"),
                already_open=item_data.get("already_open", False),
            ))
        return session

# ---- 启动器 ----

class EnvironmentLauncher:

    def __init__(self, settings: Settings):
        self.settings = settings

    def launch_environment(self, project) -> LaunchSession:
        session = LaunchSession(project_name=project.name)
        before = _snapshot_pids()

        browser_groups: dict[str, list[EnvItem]] = {}
        non_browser: list[EnvItem] = []

        for item in project.environment:
            if item.app == "browser":
                browser = (item.browser or "default").lower()
                if browser not in browser_groups:
                    browser_groups[browser] = []
                browser_groups[browser].append(item)
            else:
                non_browser.append(item)

        for browser_type, items in browser_groups.items():
            urls = [os.path.expandvars(it.target) for it in items if it.target]
            result = self._launch_browser_group(browser_type, urls)
            session.results.append(result)

        for item in non_browser:
            result = self._launch_single(item)
            session.results.append(result)

        session.tracked_pids = capture_new_processes(before, wait_seconds=2.0)
        return session

    def _launch_single(self, item: EnvItem) -> LaunchResult:
        target = os.path.expandvars(item.target) if item.target else ""
        if item.app == "vscode":
            return self._launch_vscode(target)
        elif item.app == "obsidian":
            return self._launch_obsidian(target)
        elif item.app == "browser":
            return self._launch_browser(item.browser, target)
        elif item.app == "terminal":
            return self._launch_terminal(target, item.command)
        elif item.app == "folder":
            return self._launch_folder(target)
        elif item.app == "app":
            return self._launch_app(target, item.args, item)
        return LaunchResult(env_item=item, success=False, error=f"未知类型: {item.app}")

    # ---- VSCode ----
    def _launch_vscode(self, target: str) -> LaunchResult:
        item = EnvItem(app="vscode", target=target)

        already_open, hwnd = is_vscode_folder_open(target)
        if already_open and hwnd:
            focus_window(hwnd)
            return LaunchResult(env_item=item, success=True, already_open=True)

        if target and not os.path.isdir(target):
            return LaunchResult(env_item=item, success=False, error=f"目录不存在: {target}")

        try:
            subprocess.Popen(
                f'code "{target}"', shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            )
            return LaunchResult(env_item=item, success=True)
        except Exception as e:
            return LaunchResult(env_item=item, success=False, error=str(e))

    # ---- Obsidian（读 obsidian.json 用正确 ID 切换库）----
    def _launch_obsidian(self, target: str) -> LaunchResult:
        item = EnvItem(app="obsidian", target=target)

        # 目标库主窗口已打开 → 只聚焦
        already_open, hwnd = is_obsidian_vault_open(target)
        if already_open and hwnd:
            focus_window(hwnd)
            return LaunchResult(env_item=item, success=True, already_open=True)

        obsidian_exe = find_obsidian(self.settings.obsidian_cmd)
        obs_installed = obsidian_exe.endswith(".exe") and os.path.isfile(obsidian_exe)

        # 判断 Obsidian 是否在运行
        # 窗口检测（不同版本 Obsidian 窗口标题格式不同，宽松匹配）
        obs_running = False
        try:
            import win32gui
            def _has_obsidian(hwnd, _):
                t = win32gui.GetWindowText(hwnd).lower()
                # 匹配: "myobsidian" / "xxx - Obsidian v1.x" / "Obsidian" 等
                if t.strip() and ("obsidian" in t or any(
                    _find_vault_id(p) for p in ["D:/programming/mysocial", "D:/programming/myobsidian"]
                    if _find_vault_id(p) and _find_vault_id(p) in t
                )):
                    nonlocal obs_running
                    obs_running = True
                    return False
                return True
            win32gui.EnumWindows(_has_obsidian, None)
        except Exception:
            pass

        vault_id = _find_vault_id(target)

        if obs_running:
            from urllib.parse import quote
            uri_param = quote(vault_id) if vault_id else quote(Path(target).name)
            uri = f"obsidian://open?vault={uri_param}"
            subprocess.Popen(
                f'cmd /c start "" {uri}', shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            )
        elif obs_installed:
            subprocess.Popen(
                [obsidian_exe, target],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            )
        # else: Obsidian not installed and not running — nothing to do

        return LaunchResult(env_item=item, success=True)

    # ---- 浏览器组（使用用户正常 Profile，保持登录态）----
    def _launch_browser_group(self, browser_name: str, urls: list[str]) -> LaunchResult:
        item = EnvItem(app="browser", target=urls[0] if urls else "", browser=browser_name)
        browser = browser_name.lower()

        if not urls:
            return LaunchResult(env_item=item, success=False, error="无 URL")

        browser_exe = None
        if browser and browser != "default":
            user_path = self.settings.browser_cmds.get(browser, "")
            if user_path and os.path.isfile(os.path.expandvars(user_path)):
                browser_exe = os.path.expandvars(user_path)
            else:
                browser_exe = find_browser(browser)

        if not browser_exe or not os.path.isfile(browser_exe):
            for url in urls:
                try:
                    subprocess.Popen(
                        f'cmd /c start "" "{url}"', shell=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            return LaunchResult(env_item=item, success=True,
                                error="浏览器未找到，已尝试系统默认方式打开")

        cmd = [browser_exe, "--new-window"] + urls
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            )
            return LaunchResult(env_item=item, success=True, pid=proc.pid)
        except Exception as e:
            return LaunchResult(env_item=item, success=False, error=str(e))

    # ---- 浏览器（独立进程 + 独立 Profile，关闭时杀 PID 即可） ----
    def _launch_browser(self, browser_name: str, target: str) -> LaunchResult:
        item = EnvItem(app="browser", target=target, browser=browser_name)
        browser = (browser_name or "").lower()

        browser_exe = None
        if browser and browser != "default":
            user_path = self.settings.browser_cmds.get(browser, "")
            if user_path and os.path.isfile(os.path.expandvars(user_path)):
                browser_exe = os.path.expandvars(user_path)
            else:
                browser_exe = find_browser(browser)

        if not browser_exe or not os.path.isfile(browser_exe):
            try:
                subprocess.Popen(
                    f'cmd /c start "" "{target}"', shell=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                )
                return LaunchResult(env_item=item, success=True)
            except Exception as e:
                return LaunchResult(env_item=item, success=False, error=str(e))

        import tempfile
        project_slug = "".join(c if c.isalnum() else "_" for c in item.target)[:30]
        profile_dir = os.path.join(
            tempfile.gettempdir(), "workbench-browsers", project_slug
        )
        os.makedirs(profile_dir, exist_ok=True)

        try:
            proc = subprocess.Popen(
                [
                    browser_exe,
                    f"--user-data-dir={profile_dir}",
                    "--new-window",
                    "--no-first-run",
                    "--no-default-browser-check",
                    target,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
            time.sleep(0.5)
            ret = proc.poll()
            if ret is not None and ret != 0:
                _, stderr = proc.communicate(timeout=2)
                err_msg = stderr.decode("utf-8", errors="replace")[:200]
                return LaunchResult(env_item=item, success=False,
                                    error=f"Chrome 启动失败(code={ret}): {err_msg}")
            return LaunchResult(env_item=item, success=True, pid=proc.pid)
        except Exception as e:
            return LaunchResult(env_item=item, success=False, error=str(e))

    # ---- 终端 ----
    def _launch_terminal(self, target: str, command: str) -> LaunchResult:
        item = EnvItem(app="terminal", target=target, command=command)
        terminal_exe = find_terminal(self.settings.terminal_cmd)
        terminal_name = self.settings.terminal_cmd.lower()
        dir_name = Path(target).name if target else "terminal"
        window_title = f"▸工作台-{dir_name}"

        try:
            if terminal_name == "wt" or "wt.exe" in terminal_exe.lower():
                args = [terminal_exe]
                if target:
                    args.extend(["-d", target])
                cmd_suffix = f"title {window_title}"
                if command:
                    cmd_suffix += f" && {command}"
                args.extend(["cmd", "/k", cmd_suffix])
                subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

            elif terminal_name in ("powershell", "pwsh"):
                ps_lines = [f"$Host.UI.RawUI.WindowTitle='{window_title}'"]
                if target:
                    ps_lines.append(f"cd '{target}'")
                if command:
                    ps_lines.append(command)
                subprocess.Popen(
                    [terminal_exe, "-NoExit", "-Command", "; ".join(ps_lines)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                )

            else:  # CMD
                cmd_parts = [f"title {window_title}"]
                if target:
                    cmd_parts.append(f"cd /d {target}")
                if command:
                    cmd_parts.append(command)
                subprocess.Popen(
                    [terminal_exe, "/k", " && ".join(cmd_parts)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                )

            return LaunchResult(env_item=item, success=True)
        except Exception as e:
            return LaunchResult(env_item=item, success=False, error=str(e))

    # ---- 文件夹 ----
    def _launch_folder(self, target: str) -> LaunchResult:
        item = EnvItem(app="folder", target=target)
        if not target or not os.path.isdir(target):
            return LaunchResult(env_item=item, success=False, error=f"目录不存在: {target}")
        try:
            os.startfile(target)
            return LaunchResult(env_item=item, success=True)
        except Exception as e:
            return LaunchResult(env_item=item, success=False, error=str(e))

    # ---- 任意程序（追踪 PID 用于关闭）----
    def _launch_app(self, target: str, args: str, orig_item: Optional[EnvItem] = None) -> LaunchResult:
        # 保留原始 item 的 title_kw 等字段
        item = orig_item if orig_item else EnvItem(app="app", target=target, args=args)
        expanded = os.path.expandvars(target)
        try:
            if os.path.isfile(expanded):
                cmd = [expanded] + (args.split() if args else [])
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            else:
                proc = subprocess.Popen(
                    f'start "" "{expanded}" {args}', shell=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                )
            return LaunchResult(env_item=item, success=True, pid=proc.pid)
        except Exception as e:
            return LaunchResult(env_item=item, success=False, error=str(e))