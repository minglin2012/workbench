"""应用路径查找器：自动检测常用应用的安装路径。

核心原则：始终返回完整的 .exe 路径（而非 .cmd 包装），
确保 subprocess.Popen 无需 shell=True 即可直接启动。
"""

import os
import shutil
from pathlib import Path
from typing import Optional


# 常见的浏览器安装路径（按优先级排列）
_BROWSER_SEARCH_PATHS = {
    "chrome": [
        "D:/Scoop/apps/googlechrome/current/chrome.exe",
        os.path.expandvars("%LOCALAPPDATA%/Google/Chrome/Application/chrome.exe"),
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    ],
    "edge": [
        os.path.expandvars("%PROGRAMFILES(x86)%/Microsoft/Edge/Application/msedge.exe"),
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    ],
    "firefox": [
        "D:/Scoop/apps/firefox/current/firefox.exe",
        "C:/Program Files/Mozilla Firefox/firefox.exe",
        "C:/Program Files (x86)/Mozilla Firefox/firefox.exe",
    ],
}


def _resolve_exe(name: str, search_paths: list[str]) -> Optional[str]:
    """通用的 exe 查找：先查指定路径，再查 PATH。"""
    for p in search_paths:
        expanded = os.path.expandvars(p)
        if os.path.isfile(expanded):
            return expanded

    found = shutil.which(name)
    if found and os.path.isfile(found):
        return found
    return None


def find_browser(browser_name: str) -> Optional[str]:
    """查找浏览器可执行文件路径。"""
    paths = _BROWSER_SEARCH_PATHS.get(browser_name.lower(), [])
    exe_names = {
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
        "firefox": "firefox.exe",
    }
    name = exe_names.get(browser_name.lower(), "")

    # 先尝试已知路径
    for p in paths:
        expanded = os.path.expandvars(p)
        if os.path.isfile(expanded):
            return expanded

    # 再尝试 PATH
    if name:
        found = shutil.which(name)
        if found and os.path.isfile(found):
            return found

    return None


def find_vscode(preferred_cmd: str = "code") -> str:
    """查找 VSCode 可执行文件（返回完整 .exe 路径）。

    解析顺序：
    1. 用户指定路径（如 D:/path/to/Code.exe）
    2. Scoop: code → Code.exe
    3. 标准安装路径
    4. PATH 中的 code（尝试找到其指向的 Code.exe）
    """
    # 如果用户直接给了 exe 路径
    if preferred_cmd.endswith(".exe") and os.path.isfile(preferred_cmd):
        return preferred_cmd
    expanded = os.path.expandvars(preferred_cmd)
    if os.path.isfile(expanded):
        return expanded

    # Scoop 安装：code.cmd → 找到实际 Code.exe
    scoop_code = "D:/Scoop/apps/vscode/current/Code.exe"
    if os.path.isfile(scoop_code):
        return scoop_code

    # 标准安装路径
    search_paths = [
        os.path.expandvars("%LOCALAPPDATA%/Programs/Microsoft VS Code/Code.exe"),
        os.path.expandvars("%PROGRAMFILES%/Microsoft VS Code/Code.exe"),
        os.path.expandvars("%PROGRAMFILES(x86)%/Microsoft VS Code/Code.exe"),
    ]
    for p in search_paths:
        if os.path.isfile(p):
            return p

    # 尝试通过 PATH 中的 code.cmd 找到 Code.exe
    code_cmd = shutil.which("code.cmd") or shutil.which("code")
    if code_cmd:
        # code.cmd 通常在 scoop/shims 中，尝试解析到 Code.exe
        # 也尝试直接看 code.cmd 同级或上级目录
        code_dir = Path(code_cmd).parent
        # Scoop shims: .../scoop/shims/code.cmd → .../scoop/apps/vscode/current/Code.exe
        scoop_current = code_dir.parent / "apps" / "vscode" / "current" / "Code.exe"
        if scoop_current.is_file():
            return str(scoop_current)

    # 最后回退：返回 "code"（让 cmd /c start 去解析）
    return "code"


def find_obsidian(preferred_cmd: str = "obsidian") -> str:
    """查找 Obsidian 可执行文件（返回完整 .exe 路径）。"""
    if preferred_cmd.endswith(".exe") and os.path.isfile(preferred_cmd):
        return preferred_cmd
    expanded = os.path.expandvars(preferred_cmd)
    if os.path.isfile(expanded):
        return expanded

    search_paths = [
        os.path.expandvars("%LOCALAPPDATA%/Obsidian/Obsidian.exe"),
        os.path.expandvars("%LOCALAPPDATA%/Programs/Obsidian/Obsidian.exe"),
        os.path.expandvars("%APPDATA%/Obsidian/Obsidian.exe"),
        os.path.expandvars("%LOCALAPPDATA%/obsidian/Obsidian.exe"),
        "D:/Scoop/apps/obsidian/current/Obsidian.exe",
        "C:/Program Files/Obsidian/Obsidian.exe",
        "C:/Program Files (x86)/Obsidian/Obsidian.exe",
    ]
    for p in search_paths:
        if os.path.isfile(p):
            return p

    # 尝试通过进程查找
    try:
        import subprocess
        result = subprocess.run(
            ['wmic', 'process', 'where', 'name="Obsidian.exe"', 'get', 'ExecutablePath'],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.endswith("Obsidian.exe") and os.path.isfile(line):
                return line
    except Exception:
        pass

    found = shutil.which("obsidian") or shutil.which("Obsidian")
    if found and os.path.isfile(found) and found.endswith(".exe"):
        return found

    return "obsidian"  # 回退


def find_terminal(preferred_cmd: str = "wt") -> str:
    """查找终端可执行文件（返回完整路径）。"""
    if os.path.isfile(preferred_cmd):
        return preferred_cmd

    terminal_map = {
        "wt": ["wt.exe", "wt"],
        "powershell": ["pwsh.exe", "pwsh", "powershell.exe", "powershell"],
        "cmd": ["cmd.exe", "cmd"],
    }

    names = terminal_map.get(preferred_cmd.lower(), terminal_map["wt"])
    for name in names:
        found = shutil.which(name)
        if found and os.path.isfile(found):
            return found

    # Windows Terminal 的 Store 安装路径
    wt_path = os.path.expandvars("%LOCALAPPDATA%/Microsoft/WindowsApps/wt.exe")
    if os.path.isfile(wt_path):
        return wt_path

    return "cmd.exe"
