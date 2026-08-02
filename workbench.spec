# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 构建配置 - 工作台"""

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('static/index.html', 'static'),
        ('static/style.css', 'static'),
        ('static/app.js', 'static'),
        ('projects.yaml', '.'),
        ('projects.yaml.example', '.'),
    ],
    hiddenimports=[
        'win32gui', 'win32con', 'win32process',
        'psutil', 'PIL', 'pystray', 'yaml',
        'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'starlette', 'fastapi', 'websockets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Workbench',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
