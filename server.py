"""工作台主入口：启动 FastAPI 服务 + 系统托盘图标。

用法：
    python server.py            # 普通启动
    python server.py --no-tray  # 不启动系统托盘（调试用）
"""

import argparse
import os
import sys
import threading
import webbrowser
import time
from pathlib import Path

# 确保工作目录正确
os.chdir(Path(__file__).parent)


def find_free_port(start_port: int = 8765, max_attempts: int = 20) -> int:
    """查找可用端口。"""
    import socket
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port  # 回退


def create_tray_icon(port: int):
    """创建系统托盘图标。"""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("警告: pystray 或 Pillow 未安装，跳过托盘图标")
        return None

    # 生成一个简单的图标
    def create_icon():
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 背景圆角矩形
        draw.rounded_rectangle(
            [4, 4, size - 4, size - 4],
            radius=14,
            fill=(74, 144, 217, 255),  # #4A90D9
        )
        # "W" 字母
        draw.text(
            (size // 2, size // 2),
            "W",
            fill=(255, 255, 255, 255),
            anchor="mm",
            font=None,  # 使用默认字体
        )
        return img

    def on_open(icon, item):
        """打开仪表板。"""
        webbrowser.open(f"http://127.0.0.1:{port}")

    def on_reload(icon, item):
        """重新加载配置。"""
        import urllib.request
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/reload",
                    method="POST",
                )
            )
            icon.notify("配置已重新加载", "工作台")
        except Exception:
            icon.notify("重新加载失败", "工作台")

    def on_quit(icon, item):
        """退出。"""
        icon.stop()
        os._exit(0)

    icon = pystray.Icon(
        "workbench",
        create_icon(),
        "工作台",
        menu=pystray.Menu(
            pystray.MenuItem("打开仪表板", on_open, default=True),
            pystray.MenuItem("重新加载配置", on_reload),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", on_quit),
        ),
    )
    return icon


def main():
    # === 启动日志（打包后无控制台，写文件以便排查） ===
    import tempfile, traceback
    log_path = Path(tempfile.gettempdir()) / "workbench-startup.log"
    try:
        parser = argparse.ArgumentParser(description="工作台 Workbench")
        parser.add_argument("--no-tray", action="store_true", help="不启动系统托盘")
        parser.add_argument("--port", type=int, default=0, help="指定端口（0=自动查找）")
        parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
        parser.add_argument("--config", type=str, default=None, help="指定配置文件路径（最高优先级）")
        args = parser.parse_args()

        if args.config:
            from config_loader import set_config_path
            set_config_path(args.config)
    except Exception as e:
        log_path.write_text(f"参数解析失败:\n{traceback.format_exc()}", encoding="utf-8")
        raise

    try:
        _run_app(args, log_path)
    except Exception:
        import traceback as _tb2
        log_path.write_text(f"启动崩溃:\n{_tb2.format_exc()}", encoding="utf-8")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,
                f"工作台启动失败，详情见:\n{log_path}",
                "工作台 - 启动错误", 0x10)
        except Exception:
            pass


def _ensure_user_config():
    """首次运行时，把默认配置和示例文件复制到 %APPDATA%/workbench/。"""
    import shutil
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return
    user_dir = Path(appdata) / "workbench"
    user_dir.mkdir(parents=True, exist_ok=True)

    # 查找源目录：sys._MEIPASS (PyInstaller) > __file__ 目录 (源码)
    search_dirs = [
        Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else None,
        Path(__file__).parent,
    ]

    for filename in ["projects.yaml", "projects.yaml.example"]:
        user_file = user_dir / filename
        if user_file.exists():
            continue  # 已有，不动
        for d in search_dirs:
            if d is None:
                continue
            src = d / filename
            if src.exists():
                shutil.copy2(src, user_file)
                break


def _run_app(args, log_path):
    import traceback as _tb

    # PyInstaller console=False 时 sys.stdout/stderr 为 None
    # uvicorn 的 ColourizedFormatter 需要 isatty() → 必须重定向
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    # 首次运行：把默认配置复制到用户目录
    _ensure_user_config()

    port = args.port or find_free_port()
    logs: list[str] = []

    def add_log(msg: str):
        logs.append(msg)
        log_path.write_text("\n".join(logs), encoding="utf-8")

    add_log(f"Step1: port={port}")
    try:
        from api import create_app
        app = create_app()
        add_log("Step2: app created OK")
    except Exception:
        add_log(f"Step2 FAIL:\n{_tb.format_exc()}")
        return

    try:
        import uvicorn
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
        server = uvicorn.Server(config)
        add_log("Step3: uvicorn server created")
    except Exception:
        add_log(f"Step3 FAIL:\n{_tb.format_exc()}")
        return

    def run_server():
        try:
            server.run()
        except Exception:
            logs.append(f"uvicorn crash:\n{_tb.format_exc()}")
            log_path.write_text("\n".join(logs), encoding="utf-8")

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(1.5)

    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = s.connect_ex(("127.0.0.1", port))
    s.close()
    if result == 0:
        add_log(f"Step4: server LISTENING on port {port}")
    else:
        add_log(f"Step4 FAIL: server NOT listening on port {port} (err={result})")

    url = f"http://127.0.0.1:{port}"
    if not args.no_browser:
        try:
            os.startfile(url)
        except Exception:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    if not args.no_tray:
        tray_icon = create_tray_icon(port)
        if tray_icon:
            tray_icon.run()
        else:
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    else:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
