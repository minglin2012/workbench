"""进程追踪器：快照差分法获取启动的进程 PID，支持按 PID 关闭窗口。

核心思路：
1. 启动前：快照所有 PID
2. 启动所有应用
3. 等待进程产生
4. 启动后：快照所有 PID
5. 差分 → 新 PID = 我们启动的（或子进程）
6. 关闭时：按 PID 查找窗口 → WM_CLOSE → 验证进程是否退出
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import psutil

try:
    import win32gui
    import win32con
    import win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

# 已知的应用进程名（用于过滤差分结果）
_KNOWN_APP_EXES = {
    "code.exe", "obsidian.exe",
    "chrome.exe", "msedge.exe", "firefox.exe",
    "cmd.exe", "powershell.exe", "pwsh.exe",
    "windowsterminal.exe", "wt.exe",
    "explorer.exe",
}

@dataclass
class ProcessInfo:
    """进程的实时信息。"""
    pid: int
    name: str = ""
    exe: str = ""
    status: str = ""          # running | stopped | zombie
    window_titles: list[str] = field(default_factory=list)
    is_alive: bool = True

# ---- 快照 & 差分 ----

def _snapshot_pids() -> set[int]:
    """获取当前所有 PID 集合。"""
    return {p.pid for p in psutil.process_iter()}

def capture_new_processes(before_pids: set[int],
                          wait_seconds: float = 1.5) -> list[int]:
    """等待并捕获新产生的进程 PID。

    Args:
        before_pids: 启动前的 PID 集合。
        wait_seconds: 等待进程启动的时间。

    Returns:
        新 PID 列表（已过滤系统进程和无关进程）。
    """
    time.sleep(wait_seconds)
    after_pids = _snapshot_pids()
    new_pids = after_pids - before_pids

    tracked = []
    for pid in new_pids:
        try:
            proc = psutil.Process(pid)
            name = (proc.name() or "").lower()
            # 过滤：只保留已知应用
            if name in _KNOWN_APP_EXES:
                tracked.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return tracked

# ---- 进程信息 ----

def get_process_info(pid: int) -> Optional[ProcessInfo]:
    """获取单个进程的实时信息。"""
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        exe = ""
        try:
            exe = proc.exe() or ""
        except Exception:
            pass

        status = proc.status()
        windows = _find_windows_for_pid(pid)

        return ProcessInfo(
            pid=pid,
            name=name,
            exe=exe,
            status=status,
            window_titles=windows,
            is_alive=proc.is_running(),
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ProcessInfo(pid=pid, name="", is_alive=False)

def get_all_tracked_info(pids: list[int]) -> list[dict]:
    """批量获取追踪进程的信息（用于 API 返回）。"""
    result = []
    for pid in pids:
        info = get_process_info(pid)
        result.append({
            "pid": info.pid,
            "name": info.name,
            "exe": info.exe,
            "status": info.status,
            "is_alive": info.is_alive,
            "windows": info.window_titles,
        })
    return result

# ---- 窗口查找 ----

def _find_windows_for_pid(pid: int) -> list[str]:
    """查找属于某个 PID 的所有可见窗口标题。"""
    if not HAS_WIN32:
        return []

    titles = []

    def callback(hwnd: int, _):
        try:
            _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
            if win_pid == pid and win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and title.strip():
                    titles.append(title)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(callback, None)
    return titles

# ---- 关闭 ----

def close_by_pids(pids: list[int],
                  title_rules: list[dict] | None = None) -> tuple[int, int, list[dict]]:
    """混合关闭策略：PID + 进程名 + 窗口标题。

    对每个追踪的 PID：
    1. 精确匹配该 PID 的窗口 → WM_CLOSE
    2. 若该 PID 无可见窗口但有进程名，用进程名 + 标题规则匹配 → WM_CLOSE
    （处理 VSCode/Edge 等单实例应用：窗口由已有进程创建，PID 不在追踪列表中）

    Args:
        pids: 追踪的进程 PID 列表。
        title_rules: 标题匹配规则列表 [{"name": "code.exe", "title_kw": "minglin2012"}, ...]

    Returns:
        (关闭数, 存活数, 详情列表)
    """
    if not HAS_WIN32:
        return 0, len(pids), []

    # 展开子进程：Electron 应用（Doubao、Cherry Studio 等）的窗口属于子进程
    all_pids = set(pids)
    for pid in pids:
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                all_pids.add(child.pid)
        except Exception:
            pass

    # 收集追踪的进程名
    tracked_names: dict[str, set[str]] = {}  # pid_str → {进程名的小写版本}
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            tracked_names[str(pid)] = {proc.name().lower()}
        except Exception:
            tracked_names[str(pid)] = set()

    # 收集所有追踪进程名的并集
    all_tracked_names: set[str] = set()
    for names in tracked_names.values():
        all_tracked_names.update(names)

    # 构建标题规则的快速查找表
    name_keywords: dict[str, list[str]] = {}
    title_only_kw: list[str] = []  # 无进程名限制的纯标题关键词
    if title_rules:
        for rule in title_rules:
            proc_name = rule.get("name", "").lower()
            kw = rule.get("title_kw", "").lower()
            if not kw:
                continue
            if proc_name:
                if proc_name not in name_keywords:
                    name_keywords[proc_name] = []
                if kw not in name_keywords[proc_name]:
                    name_keywords[proc_name].append(kw)
            else:
                if kw not in title_only_kw:
                    title_only_kw.append(kw)

    all_rule_names = set(name_keywords.keys())

    # 1. 枚举窗口，发送 WM_CLOSE
    to_close: set[int] = set()  # hwnds
    found_pids: set[int] = set()

    def callback(hwnd: int, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title or not title.strip():
                return True

            _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
            title_lower = title.lower()

            # 策略 A：精确 PID 匹配 + 强制标题验证
            if win_pid in all_pids:
                # 任何 PID 匹配都必须加上标题关键词验证。
                # Chrome/Edge 主进程的一个 PID 对应所有窗口，无过滤 = 全关。
                all_kw = {kw for kws in name_keywords.values() for kw in kws}
                if all_kw and not any(kw in title_lower for kw in all_kw):
                    return True  # 标题不匹配 → 跳过
                if all_kw:  # 有关键词且匹配 → 关闭
                    to_close.add(hwnd)
                    found_pids.add(win_pid)
                    return True
                # 没有关键词（极端情况）→ 不关，安全优先
                return True

            # 策略 B + C：进程名/纯标题关键词匹配
            if not title_rules:
                return True

            # 尝试获取进程名（可能失败：Electron 沙箱、AppContainer 等）
            win_proc_name = ""
            try:
                win_proc_name = psutil.Process(win_pid).name().lower()
            except Exception:
                pass

            # 策略 B：进程名 + 标题关键词
            if win_proc_name:
                if win_proc_name in all_tracked_names or win_proc_name in all_rule_names:
                    keywords = name_keywords.get(win_proc_name, [])
                    for kw in keywords:
                        if kw in title_lower:
                            to_close.add(hwnd)
                            found_pids.add(win_pid)
                            return True

            # 策略 C：纯标题关键词（psutil 失败或进程名不匹配时）
            for kw in title_only_kw:
                if kw in title_lower:
                    to_close.add(hwnd)
                    found_pids.add(win_pid)
                    return True

        except Exception:
            pass
        return True

    win32gui.EnumWindows(callback, None)

    # 发送 WM_CLOSE（最多重试 3 次，处理浏览器自动恢复）
    for attempt in range(3):
        for hwnd in to_close:
            try:
                if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        time.sleep(0.8)

        # 检查是否还有存活的匹配窗口
        still_there = False
        for hwnd in to_close:
            try:
                if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                    still_there = True
                    break
            except Exception:
                pass
        if not still_there:
            break

    # 2. 等待窗口响应

    # 3. 检查结果
    details = []
    still_alive = 0
    closed_count = 0

    for pid in all_pids:
        info = _check_pid_after_close(pid)
        details.append(info)
        if info["still_alive"]:
            still_alive += 1
        else:
            closed_count += 1

    return closed_count, still_alive, details

# 已知浏览器进程名
_BROWSER_NAMES = {"chrome.exe", "msedge.exe", "firefox.exe"}

def _close_browser_windows_by_title(
    title_rules: list[dict],
) -> int:
    """直接按标题匹配关闭浏览器窗口（完全独立于 PID 追踪）。

    核心逻辑：遍历所有可见窗口 → 标题含任一关键词 → WM_CLOSE。
    不依赖进程名（浏览器进程可能不可访问）。
    重试 4 轮确保顽固窗口（如 Edge Startup boost）被关闭。
    """
    if not HAS_WIN32:
        return 0

    # 收集所有浏览器关键词（忽略进程名——浏览器进程经常无法访问）
    all_keywords: list[str] = []
    for rule in title_rules:
        name = rule.get("name", "").lower()
        if name in _BROWSER_NAMES:
            kw = rule.get("title_kw", "").lower()
            if kw and kw not in all_keywords:
                all_keywords.append(kw)

    if not all_keywords:
        return 0

    last_count = 0

    for attempt in range(4):
        closed_this_round = 0

        def callback(hwnd: int, _):
            nonlocal closed_this_round
            try:
                if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    return True
                title = win32gui.GetWindowText(hwnd)
                if not title or not title.strip():
                    return True
                title_lower = title.lower()

                # 检查标题是否包含任一关键词
                matched = any(kw in title_lower for kw in all_keywords)
                if not matched:
                    return True

                # 额外确认：这确实是浏览器窗口（进程名检查可选）
                _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    proc_name = psutil.Process(win_pid).name().lower()
                    if proc_name not in _BROWSER_NAMES and proc_name:
                        # 非浏览器进程，但标题匹配 → 仍关闭（可能是 WebView/Electron）
                        pass
                except Exception:
                    # 无法获取进程名（Edge 的 AppContainer 隔离）→ 仍关闭
                    pass

                # 发送关闭消息
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                try:
                    win32gui.SendMessageTimeout(
                        hwnd, win32con.WM_CLOSE, 0, 0,
                        win32con.SMTO_ABORTIFHUNG, 2000,
                    )
                except Exception:
                    pass
                closed_this_round += 1
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
        last_count = closed_this_round

        if closed_this_round == 0:
            break
        time.sleep(1.0)

    return last_count

def _check_pid_after_close(pid: int) -> dict:
    """检查 PID 在关闭后是否还活着。"""
    try:
        proc = psutil.Process(pid)
        alive = proc.is_running()
        name = proc.name()
        # 检查是否还有窗口
        windows_left = _find_windows_for_pid(pid)
        return {
            "pid": pid,
            "name": name,
            "still_alive": alive and len(windows_left) > 0,
            "windows_left": len(windows_left),
            "window_titles": windows_left[:3],
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {
            "pid": pid,
            "name": "?",
            "still_alive": False,
            "windows_left": 0,
            "window_titles": [],
        }