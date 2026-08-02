"""窗口检测器：检测应用窗口是否已打开，支持去重、聚焦和按 PID 关闭。

使用 win32gui 遍历 Windows 窗口。
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import win32gui
    import win32con
    import win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int = 0


def _get_all_visible_windows() -> list[WindowInfo]:
    """获取所有可见的顶层窗口列表。"""
    windows: list[WindowInfo] = []

    def callback(hwnd: int, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            if win32gui.IsIconic(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title or not title.strip():
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            windows.append(WindowInfo(hwnd=hwnd, title=title, pid=pid))
        except Exception:
            pass
        return True

    if HAS_WIN32:
        win32gui.EnumWindows(callback, None)
    return windows


# ---- 去重检测 ----

def is_vscode_folder_open(folder_path: str) -> tuple[bool, Optional[int]]:
    """检查 VSCode 是否已打开指定文件夹。"""
    if not HAS_WIN32:
        return False, None

    folder_name = Path(folder_path).name.lower()

    for win in _get_all_visible_windows():
        title_lower = win.title.lower()
        # VSCode 窗口特征：标题末尾是 "Visual Studio Code" 或包含文件夹名
        is_vscode = ("visual studio code" in title_lower or
                     title_lower.rstrip().endswith("code"))
        if not is_vscode:
            # 更精确：检查 " — Visual Studio Code" 模式
            if "visual studio code" not in title_lower:
                continue

        if folder_name in title_lower:
            return True, win.hwnd

    return False, None


def is_obsidian_vault_open(vault_path: str) -> tuple[bool, Optional[int]]:
    """检查 Obsidian 是否已打开指定库。

    必须同时满足：标题含库名 + 含 " - Obsidian"（主窗口特征），
    排除弹窗/设置窗口等非主窗口误匹配。
    """
    if not HAS_WIN32:
        return False, None

    vault_name = Path(vault_path).name.lower()

    for win in _get_all_visible_windows():
        title_lower = win.title.lower()
        # 必须同时含库名和 " - Obsidian"（主窗口格式）
        if vault_name in title_lower and " - obsidian" in title_lower:
            return True, win.hwnd

    return False, None


def is_browser_url_open(url: str, browser_name: str = "chrome") -> tuple[bool, Optional[int]]:
    """检查浏览器是否有可见窗口（启发式）。"""
    if not HAS_WIN32:
        return False, None

    browser_keywords = {
        "chrome": ["google chrome", "chrome"],
        "edge": ["microsoft edge", "edge"],
        "firefox": ["mozilla firefox", "firefox"],
    }
    keywords = browser_keywords.get(browser_name.lower(), [browser_name.lower()])

    for win in _get_all_visible_windows():
        title_lower = win.title.lower()
        for kw in keywords:
            if kw in title_lower:
                return True, win.hwnd

    return False, None


# ---- 聚焦 ----

def focus_window(hwnd: int) -> bool:
    """将窗口带到前台（后台线程，不阻塞）。"""
    if not HAS_WIN32:
        return False

    import threading

    def _focus():
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

    t = threading.Thread(target=_focus, daemon=True)
    t.start()
    return True


# ---- 关闭 ----

def close_window_gracefully(hwnd: int) -> bool:
    """发送 WM_CLOSE 消息给窗口（非阻塞）。"""
    if not HAS_WIN32:
        return False
    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return True
    except Exception:
        return False


def close_windows_by_session(session_results) -> tuple[int, int]:
    """根据会话中的环境组件，关闭匹配的窗口。

    按窗口标题匹配：
    - VSCode:    标题含目标文件夹名 + "Visual Studio Code"
    - Terminal:  标题含 "▸工作台-" 前缀 → 精确匹配；或含目录名 + 终端特征
    - Obsidian:  标题含库名 + "Obsidian"
    - Browser:   标题含 URL 的 hostname（如 "localhost"）
    - Folder:    标题是文件夹名

    Args:
        session_results: LaunchResult 列表

    Returns:
        (关闭的窗口数, 未匹配到的组件数)
    """
    if not HAS_WIN32 or not session_results:
        return 0, len(session_results) if session_results else 0

    # 构建匹配规则
    rules = []
    for r in session_results:
        if not r.success or r.already_open:
            continue
        item = r.env_item

        if item.app == "vscode" and item.target:
            folder_name = Path(item.target).name.lower()
            rules.append(("vscode", folder_name, item.target))

        elif item.app == "obsidian" and item.target:
            vault_name = Path(item.target).name.lower()
            rules.append(("obsidian", vault_name, item.target))

        elif item.app == "terminal":
            # 优先匹配我们自定义的 "▸工作台-" 前缀
            if item.target:
                dir_name = Path(item.target).name.lower()
                rules.append(("terminal_tag", f"▸工作台-{dir_name}", item.target))
                # 也加一条普通匹配作为回退
                rules.append(("terminal", dir_name, item.target))
            elif item.command:
                rules.append(("terminal_cmd", item.command.split()[0].lower(), item.command))

        elif item.app == "browser" and item.target:
            # 从 URL 中提取 hostname 用于匹配
            hostname = _extract_hostname(item.target)
            if hostname:
                rules.append(("browser", hostname, item.target))

        elif item.app == "folder" and item.target:
            dir_name = Path(item.target).name.lower()
            rules.append(("folder", dir_name, item.target))

    if not rules:
        return 0, len(session_results)

    windows = _get_all_visible_windows()
    closed_hwnds = set()
    matched_rules = set()

    for win in windows:
        title_lower = win.title.lower()

        for i, (rule_type, keyword, full_target) in enumerate(rules):
            if i in matched_rules:
                continue

            should_close = False

            if rule_type == "vscode":
                if keyword in title_lower and "visual studio code" in title_lower:
                    should_close = True

            elif rule_type == "obsidian":
                if keyword in title_lower and "obsidian" in title_lower:
                    should_close = True

            elif rule_type == "terminal_tag":
                # 精确匹配 "▸工作台-xxx" 前缀
                if keyword in title_lower:
                    should_close = True

            elif rule_type == "terminal":
                # 回退：匹配目录名 + 终端特征
                if keyword in title_lower:
                    is_term = any(t in title_lower for t in [
                        "windows powershell", "powershell",
                        "command prompt", "cmd.exe",
                        "windows terminal", "wt.exe",
                        "▸工作台-",  # 也匹配我们的标签
                    ])
                    should_close = is_term

            elif rule_type == "terminal_cmd":
                if keyword in title_lower:
                    is_term = any(t in title_lower for t in [
                        "windows powershell", "powershell",
                        "command prompt", "cmd.exe",
                        "windows terminal", "wt.exe",
                        "▸工作台-",
                    ])
                    should_close = is_term

            elif rule_type == "browser":
                # 浏览器窗口标题通常含 hostname + 浏览器名
                if keyword in title_lower:
                    is_browser = any(b in title_lower for b in [
                        "google chrome", "chrome",
                        "microsoft edge", "microsoft​ edge", "edge",
                        "mozilla firefox", "firefox",
                    ])
                    if is_browser:
                        should_close = True

            elif rule_type == "folder":
                if keyword in title_lower:
                    should_close = True

            if should_close and win.hwnd not in closed_hwnds:
                close_window_gracefully(win.hwnd)
                closed_hwnds.add(win.hwnd)
                matched_rules.add(i)
                # 不要 break——同一个窗口可能匹配多条规则（如浏览器窗口）
                break

    closed_count = len(closed_hwnds)
    unmatched = len(rules) - len(matched_rules)
    return closed_count, unmatched


def _extract_hostname(url: str) -> str:
    """从 URL 中提取 hostname。

    Examples:
        http://localhost:3000 → "localhost"
        https://github.com/trending → "github.com"
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return host.lower()
    except Exception:
        return ""
