"""配置加载器：读取、校验 YAML 配置文件，支持热重载。"""

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# 配置文件路径优先级（从高到低）：
# 1. set_config_path() 显式设置（如 CLI --config 参数）
# 2. %APPDATA%/workbench/projects.yaml（用户自定义）
# 3. 同目录 projects.yaml（开发/便携/默认）
#
# 优先级 2 仅在文件已存在时生效（用户已自定义）。
# 首次使用时，优先级 3 的默认配置会被自动复制到优先级 2。
_override_config_path: Optional[Path] = None


def set_config_path(path: Path | str | None):
    """显式设置配置文件路径（最高优先级）。"""
    global _override_config_path
    _override_config_path = Path(path) if path else None


def _resolve_config_path() -> Path:
    """按优先级解析配置文件路径。"""
    # 1. 显式覆盖
    if _override_config_path and _override_config_path.exists():
        return _override_config_path

    # 2. 用户自定义配置
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        user_path = Path(appdata) / "workbench" / "projects.yaml"
        if user_path.exists():
            return user_path

    # 3. 默认配置
    local_path = Path(__file__).parent / "projects.yaml"
    # 如果在 PyInstaller 打包中，尝试 sys._MEIPASS
    if not local_path.exists():
        import sys
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            bundled = Path(meipass) / "projects.yaml"
            if bundled.exists():
                return bundled
    return local_path


def _user_config_dir() -> Path:
    """用户配置目录（%APPDATA%/workbench/），自动创建。"""
    appdata = os.environ.get("APPDATA", str(Path.home()))
    d = Path(appdata) / "workbench"
    d.mkdir(parents=True, exist_ok=True)
    return d


# 每次调用 load_config 时重新解析（支持热切换）
# 不在模块加载时固化路径


@dataclass
class EnvItem:
    """项目环境中的一个组件（一个 app 启动项）。"""
    app: str            # vscode | obsidian | browser | terminal | folder | app
    target: str = ""    # 目标路径/URL
    command: str = ""   # 可选：要执行的命令（terminal/app 类型）
    browser: str = "default"  # chrome | edge | firefox | default
    args: str = ""      # 可选：命令行参数
    title_kw: str = ""  # 可选：关闭时匹配窗口标题的关键词（app 类型中文名等）


@dataclass
class Project:
    """一个项目环境。"""
    name: str
    icon: str = "📁"
    color: str = "#4A90D9"
    category: str = "其他"
    environment: list[EnvItem] = field(default_factory=list)


@dataclass
class Settings:
    """全局设置。"""
    window_width: int = 900
    window_height: int = 680
    theme: str = "dark"
    columns: int = 4
    autostart: bool = False
    vscode_cmd: str = "code"
    obsidian_cmd: str = "obsidian"
    terminal_cmd: str = "wt"
    browser_cmds: dict = field(default_factory=lambda: {
        "chrome": "",
        "edge": "",
        "firefox": ""
    })


@dataclass
class Config:
    """完整的配置对象。"""
    settings: Settings = field(default_factory=Settings)
    projects: list[Project] = field(default_factory=list)


def _parse_env_item(data: dict) -> EnvItem:
    """从 YAML 字典解析单个环境组件。"""
    result = EnvItem(
        app=data.get("app", ""),
        target=data.get("target", ""),
        command=data.get("command", ""),
        browser=data.get("browser", "default"),
        args=data.get("args", ""),
        title_kw=data.get("title_kw", ""),
    )
    return result


def _parse_settings(data: dict) -> Settings:
    """从 YAML 字典解析全局设置。"""
    return Settings(
        window_width=data.get("window_width", 900),
        window_height=data.get("window_height", 680),
        theme=data.get("theme", "dark"),
        columns=data.get("columns", 4),
        autostart=data.get("autostart", False),
        vscode_cmd=data.get("vscode_cmd", "code"),
        obsidian_cmd=data.get("obsidian_cmd", "obsidian"),
        terminal_cmd=data.get("terminal_cmd", "wt"),
        browser_cmds=data.get("browser_cmds", {
            "chrome": "",
            "edge": "",
            "firefox": ""
        }),
    )


def load_config(path: Optional[Path] = None) -> Config:
    """加载并校验配置文件。

    Args:
        path: 配置文件路径。不传则按优先级自动解析。

    Returns:
        Config 对象。

    Raises:
        FileNotFoundError: 配置文件不存在。
        yaml.YAMLError: YAML 格式错误。
        ValueError: 配置内容无效。
    """
    path = path or _resolve_config_path()

    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ValueError("配置文件为空")

    config = Config()

    # 解析 settings
    if "settings" in raw and raw["settings"]:
        config.settings = _parse_settings(raw["settings"])

    # 解析 projects
    if "projects" in raw and raw["projects"]:
        for proj_data in raw["projects"]:
            if not proj_data or not proj_data.get("name"):
                continue
            env_items = []
            if "environment" in proj_data and proj_data["environment"]:
                for item_data in proj_data["environment"]:
                    if item_data and item_data.get("app"):
                        env_items.append(_parse_env_item(item_data))
            config.projects.append(Project(
                name=proj_data.get("name", ""),
                icon=proj_data.get("icon", "📁"),
                color=proj_data.get("color", "#4A90D9"),
                category=proj_data.get("category", "其他"),
                environment=env_items,
            ))

    return config


def get_mod_time() -> float:
    """获取配置文件最后修改时间（用于热重载检测）。"""
    try:
        return os.path.getmtime(_resolve_config_path())
    except OSError:
        return 0.0
