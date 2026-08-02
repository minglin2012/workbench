# ⚡ 工作台 (Workbench)

> 一键切换项目环境 —— VSCode、Obsidian、浏览器、终端、任意程序，整齐划一。

当你需要在多个项目之间切换时，不必手动打开一个个窗口——工作台把每个项目需要的所有软件、目录、URL 打包成一个**项目环境**，一键启动，再一键安全关闭。

---

## 为什么需要它？

```
传统方式：打开 VSCode → 打开终端 → 运行 dev server → 打开浏览器 →
         切 Obsidian 查笔记 → 切另一个项目 → 关掉之前的窗口...
工作台：  点「发博客」→ 全部自动打开
         点「私人秘书」→ 旧的安全关闭，新的自动打开
```

## 功能

- **多应用环境** — 一个项目可包含 VSCode + 终端 + 浏览器 + Obsidian + 任意程序
- **安全切换** — 切换项目时 WM_CLOSE 优雅关闭，不丢失未保存数据
- **进程追踪** — 快照差分法追踪启动的进程，实时显示 PID/窗口绑定
- **去重检测** — 已打开的窗口自动聚焦，不重复打开
- **历史记录** — 一键恢复历史会话
- **系统托盘** — 最小化到托盘，右键快速切换
- **浏览器隔离** — 同项目同浏览器只启一个进程，多 URL 作为标签页
- **暗色主题** — Web UI，玻璃态卡片设计

## 快速开始

### 安装

下载 [最新 Release](https://github.com/minglin2012/workbench/releases) 中的 `Workbench-Setup-x.x.x.exe`，双击安装。

或直接运行便携版 `Workbench.exe`（无需安装）。

### 源码运行

```powershell
git clone https://github.com/minglin2012/workbench.git
cd workbench
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
python server.py
```

浏览器自动打开 `http://127.0.0.1:8765`。

### 一键打包

```bat
.\build.bat
```

## 配置项目

编辑 `%APPDATA%\workbench\projects.yaml`（安装版）或源码目录 `projects.yaml`：

```yaml
settings:
  theme: "dark"
  vscode_cmd: "code"
  terminal_cmd: "wt"

projects:
  - name: "我的项目"
    icon: "🚀"
    color: "#FF6B6B"
    category: "开发"
    environment:
      - app: "vscode"
        target: "D:/path/to/project"
      - app: "terminal"
        target: "D:/path/to/project"
        command: "npm run dev"
      - app: "browser"
        browser: "chrome"
        target: "http://localhost:3000"
```

### 支持的应用类型

| app | 说明 | 参数 |
|-----|------|------|
| `vscode` | VS Code 打开文件夹 | `target`: 目录路径 |
| `obsidian` | Obsidian 打开库 | `target`: 库路径 |
| `browser` | 浏览器打开 URL | `target`: URL, `browser`: chrome/edge/firefox/default |
| `terminal` | 终端执行命令 | `target`: 工作目录, `command`: 命令 |
| `folder` | 资源管理器打开 | `target`: 目录路径 |
| `app` | 任意程序 | `target`: exe 路径, `args`: 参数, `title_kw`: 关闭关键词 |

完整示例见 [`projects.yaml.example`](projects.yaml.example)。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10 + FastAPI + uvicorn |
| 前端 | Vanilla HTML/CSS/JS |
| 进程管理 | psutil + win32gui + win32process |
| 打包 | PyInstaller (exe) + Inno Setup (安装包) |
| CI/CD | GitHub Actions |

## License

MIT
