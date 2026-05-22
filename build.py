#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打包 ChatCFD 为可执行程序 (PyInstaller)。

参照 SimGraph 的 build.py 设计，适配 ChatCFD 的双服务架构。

打包模式
--------
默认 **onedir**：产出 dist/chatcfd/ 文件夹 (chatcfd.exe + _internal/)。
  - 启动快，无需每次解压；VTK 的 DLL 布局稳定，加载可靠；不易被杀毒误拦。
  - 交付：把整个 dist/chatcfd/ 文件夹发给用户。
加 --onefile 切换到单文件 exe（181MB，冷启动慢，VTK DLL 加载易出问题，不推荐）。

设计要点
--------
1. **单 exe / 单文件夹，子命令路由**：launcher 按 argv 路由：
       chatcfd.exe post    -> 后处理服务 (FastAPI, 8001)
       chatcfd.exe agent   -> Agent 服务 (FastAPI WebSocket, 8090)
       chatcfd.exe         -> 同时起两个 + 开浏览器
   start.bat 用 ``chatcfd.exe post`` / ``chatcfd.exe agent`` 拉起两个窗口。

2. **`-m module` 陷阱**：PyInstaller bootloader 不认 ``-m``。原 start.bat 的
   ``python -m uvicorn`` 在 frozen 下必失败。launcher 改为直接 ``uvicorn.run``；
   自旋子进程用裸子命令 ``post``。mempalace 的 stdio 子进程同样踩坑 —— 打包版
   默认 MEMPALACE_ENABLED=false。

3. **自研 VTK**：Romtek C++ (vtkRomtekIODriver / vtkRomtekAnalysis /
   vtkRomtekVtkAlgorithm) 编译进自定义 VTK build，作为 ``vtk`` 模块属性暴露。
   125 个 .pyd + 162 个 .dll 全在 site-packages/vtkmodules/。仅靠
   ``collect_all('vtk')`` + ``collect_all('vtkmodules')`` 收集 —— **不要**再用
   binaries= 手动塞 .pyd，否则 .pyd 同时被当扩展模块和普通二进制，加载冲突。

4. **算法插件按文件路径加载**：``algorithm_registry.scan_and_load`` 用
   ``importlib`` 从 post_service/algorithms/*.py 读盘加载。这些 .py 当 data
   文件打进去，且它们 import 的 vtk/numpy/PIL/matplotlib 进 hidden-imports。

5. **数据文件**：web/dist / post_service/algorithms/*.py / post_service/config
   用 datas 打进去。server.py / physical_mapping.py 用 os.path.dirname(__file__)
   定位，frozen 下自然指向对应路径。

运行
----
必须在 PostProcessTool 环境里跑（collect_all 需要能 import vtk/litellm）：

    conda activate PostProcessTool
    python build.py                 # onedir (推荐)
    python build.py --onefile       # 单文件 exe
    python build.py --skip-frontend # 跳过 npm 构建

产出：onedir -> dist/chatcfd/ (含 chatcfd.exe/.env/start.bat/README.txt)
      onefile -> dist/ (chatcfd.exe + .env/start.bat/README.txt)
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.dirname(__file__))
WEB_DIR = os.path.join(ROOT, "web")
WEB_DIST = os.path.join(WEB_DIR, "dist")
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")
LAUNCHER = os.path.join(BUILD, "chatcfd_launcher.py")
TARGET_NAME = "chatcfd"


# ---------------------------------------------------------------------------
# 1) 前端构建：npm run build -> web/dist
# ---------------------------------------------------------------------------

def step_frontend(skip):
    print("\n[1/5] 构建前端 (web/dist)")
    if skip:
        print("  跳过 (--skip-frontend)")
    else:
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            raise SystemExit("找不到 npm。请先装 Node.js，或加 --skip-frontend。")
        if not os.path.isdir(os.path.join(WEB_DIR, "node_modules")):
            print("  安装 npm 依赖 ...")
            subprocess.check_call([npm, "install"], cwd=WEB_DIR)
        subprocess.check_call([npm, "run", "build"], cwd=WEB_DIR)
    if not os.path.isfile(os.path.join(WEB_DIST, "index.html")):
        raise SystemExit("web/dist/index.html 不存在 —— 前端未构建成功。")
    print("  前端就绪: " + WEB_DIST)


# ---------------------------------------------------------------------------
# 2) 清理旧产物
# ---------------------------------------------------------------------------

def step_clean():
    print("\n[2/5] 清理 build/ dist/ *.spec")
    for d in (DIST, BUILD):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    for fn in os.listdir(ROOT):
        if fn.endswith(".spec"):
            try:
                os.remove(os.path.join(ROOT, fn))
            except OSError:
                pass
    os.makedirs(BUILD, exist_ok=True)


def step_clean_spec():
    import glob
    for sp in glob.glob(os.path.join(ROOT, "*.spec")):
        try:
            os.remove(sp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 3) 生成 launcher
# ---------------------------------------------------------------------------

LAUNCHER_CODE = '''\
# -*- coding: utf-8 -*-
"""PyInstaller 入口 —— 由 build.py 生成。

子命令路由:
  chatcfd.exe post   -> 后处理服务 (FastAPI, 默认 8001)
  chatcfd.exe agent  -> Agent 服务 (FastAPI WebSocket, 默认 8090)
  chatcfd.exe        -> post 在新窗口 + agent 在本窗口 + 自动开浏览器

frozen 注意:
  - basedir = chatcfd.exe 所在目录; .env 从这里加载。
  - PyInstaller bootloader 不认 `-m module`; 自旋子进程用裸子命令 `post`
    (frozen 下 sys.executable == chatcfd.exe)。
"""
import os
import sys


if getattr(sys, "frozen", False):
    basedir = os.path.dirname(os.path.realpath(sys.executable))
else:
    basedir = os.path.abspath(os.path.dirname(__file__))

# 在 import app 模块前加载 .env (server.py / agent/main.py 在 import 期读 env)
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(basedir, ".env")
    if os.path.isfile(_env_path):
        load_dotenv(_env_path, override=True)
        print("[launcher] loaded .env:", _env_path)
    else:
        print("[launcher] .env not found at", _env_path)
except Exception as _e:
    print("[launcher] .env load skipped:", _e)

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
# 打包版默认关 mempalace —— 它的 stdio 子进程用 `-m`, frozen 下跑不起来。
os.environ.setdefault("MEMPALACE_ENABLED", "false")


def _post_port():
    return int(os.environ.get("POST_SERVICE_PORT", "8001"))


def _agent_port():
    return int(os.environ.get("AGENT_PORT", "8090"))


def run_post():
    import uvicorn
    from post_service.server import app
    print("[ChatCFD] Post Service starting on port", _post_port())
    uvicorn.run(app, host="0.0.0.0", port=_post_port())


def run_agent():
    import uvicorn
    from agent.main import app
    print("[ChatCFD] Agent Service starting on port", _agent_port())
    uvicorn.run(app, host="0.0.0.0", port=_agent_port())


def run_both():
    import subprocess
    import time
    import webbrowser

    flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    print("[ChatCFD] launching Post Service in a separate window ...")
    post = subprocess.Popen([sys.executable, "post"], creationflags=flags)
    try:
        time.sleep(8)
        url = "http://localhost:" + str(_post_port())
        print("[ChatCFD] opening", url)
        try:
            webbrowser.open(url)
        except Exception:
            pass
        run_agent()
    finally:
        print("[ChatCFD] stopping Post Service ...")
        try:
            post.terminate()
        except Exception:
            pass


def main():
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if cmd == "post":
        run_post()
    elif cmd == "agent":
        run_agent()
    else:
        run_both()


if __name__ == "__main__":
    main()
'''


def step_launcher():
    print("\n[3/5] 写 launcher: " + LAUNCHER)
    with open(LAUNCHER, "w", encoding="utf-8") as f:
        f.write(LAUNCHER_CODE)


# ---------------------------------------------------------------------------
# 4) PyInstaller
# ---------------------------------------------------------------------------

# collect_all / collect_submodules 目标。test-import 失败的 optional 库静默跳过。
_OPTIONAL_LIBS = [
    # VTK —— post_service 核心；自研 Romtek 模块就在 vtkmodules 里。
    # 只用 collect_all，不要再用 binaries= 手动塞 .pyd。
    ("vtk", [("all", "vtk"), ("all", "vtkmodules")]),
    # litellm —— Agent 调 LLM；子模块 + 模型价格 json 多，必须 collect_all。
    ("litellm", [("all", "litellm")]),
    # MCP 协议栈
    ("mcp", [("submodules", "mcp"), ("data", "mcp")]),
    ("fastmcp", [("submodules", "fastmcp"), ("data", "fastmcp")]),
    # matplotlib —— probe_line.py 出图；mpl-data (字体/样式) 要 collect_all。
    ("matplotlib", [("all", "matplotlib")]),
    # tiktoken —— litellm token 计数；扩展模块易漏。
    ("tiktoken", [("submodules", "tiktoken")]),
    ("tiktoken_ext", [("submodules", "tiktoken_ext")]),
]

_REQUIRED_LIBS = ["vtk"]

_BASE_HIDDEN_IMPORTS = [
    # --- 自身两个包 ---
    "post_service.server",
    "agent.main",
    # --- VTK ---
    "vtk",
    "vtk.util",
    "vtk.util.numpy_support",
    "vtkmodules.all",
    "vtkmodules.util",
    "vtkmodules.util.numpy_support",
    # --- 算法插件按文件路径加载, 静态分析看不到其 import ---
    "numpy",
    "PIL",
    "PIL.Image",
    "matplotlib",
    "matplotlib.pyplot",
    "csv",
    # --- uvicorn 运行期动态 import ---
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # --- web / mcp / 异步栈 ---
    "fastapi",
    "starlette",
    "sse_starlette",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    "anyio",
    "anyio._backends",
    "anyio._backends._asyncio",
    "httpx",
    "dotenv",
    # --- LLM ---
    "litellm",
    "tiktoken_ext.openai_public",
]

_EXCLUDES = [
    "pytest",
    "PyInstaller",
    # VTK 探测的 GUI 后端 —— 一个都不需要, 排除掉减少噪音和体积。
    "wx",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "tkinter",
]

# 让 importlib.metadata.version("X") 在 frozen 下能查到版本 —— 不少三方库
# __init__.py 会读自身 dist-info, 缺了直接 PackageNotFoundError 崩进程。
_METADATA_PKGS = [
    "fastapi", "starlette", "uvicorn", "anyio", "sniffio", "h11", "httpx",
    "httpcore", "click", "certifi", "pydantic", "pydantic-core",
    "mcp", "fastmcp", "sse-starlette",
    "litellm", "openai", "tiktoken", "tokenizers",
    "numpy", "matplotlib", "pillow",
    "python-dotenv", "websockets",
]


def _collect_dir(src_dir, dest_prefix, exts=None):
    """把一个目录下的文件收成 spec datas= 的 (src, dest) 对。"""
    out = []
    if not os.path.isdir(src_dir):
        return out
    for dirpath, _dn, filenames in os.walk(src_dir):
        if "__pycache__" in dirpath:
            continue
        rel = os.path.relpath(dirpath, src_dir)
        target = dest_prefix if rel in (".", "") else \
            dest_prefix + "/" + rel.replace(os.sep, "/")
        for fn in filenames:
            if fn.endswith((".pyc", ".pyo")):
                continue
            if exts and not fn.lower().endswith(exts):
                continue
            out.append((os.path.join(dirpath, fn), target))
    return out


# onedir / onefile 的 EXE/COLLECT 段不同，分别给模板。
_EXE_ONEFILE = '''
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='{target_name}',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    upx_exclude=[], runtime_tmpdir=None, console=True,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
'''

_EXE_ONEDIR = '''
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='{target_name}',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[], name='{target_name}',
)
'''

_SPEC_TEMPLATE = '''# Auto-generated by build.py — do not edit manually.
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import (
    collect_submodules, collect_data_files, collect_all, copy_metadata,
)

block_cipher = None

_extra_hidden_imports = []
_extra_datas = []
_extra_binaries = []

for kind, pkg in {collect_alls!r}:
    if kind == 'submodules':
        _extra_hidden_imports += collect_submodules(pkg)
    elif kind == 'data':
        _extra_datas += collect_data_files(pkg)
    elif kind == 'all':
        _d, _b, _h = collect_all(pkg)
        _extra_datas += _d
        _extra_binaries += _b
        _extra_hidden_imports += _h

for _pkg in {metadata_pkgs!r}:
    try:
        _extra_datas += copy_metadata(_pkg)
    except Exception:
        pass


a = Analysis(
    [r'{launcher}'],
    pathex=[r'{root}'],
    binaries=_extra_binaries,
    datas={datas!r} + _extra_datas,
    hiddenimports={hidden_imports!r} + _extra_hidden_imports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes={excludes!r},
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
{exe_section}'''


def _write_spec(spec_path, onefile):
    hidden_imports = list(_BASE_HIDDEN_IMPORTS)
    collect_alls = []
    datas = []

    for mod_name, jobs in _OPTIONAL_LIBS:
        try:
            __import__(mod_name)
        except ImportError:
            if mod_name in _REQUIRED_LIBS:
                raise SystemExit(
                    "[FATAL] 必需库 {} 未安装/不可 import。"
                    "请确认在 PostProcessTool 环境里运行 build.py。".format(mod_name)
                )
            print("  [optional 缺] {} —— 相关功能打包后不可用".format(mod_name))
            continue
        collect_alls.extend(jobs)

    # 自身两个包全量收子模块 (algorithms/ 走 datas, 但收 submodules 保依赖链)
    collect_alls.append(("submodules", "post_service"))
    collect_alls.append(("submodules", "agent"))

    # 数据文件
    datas.extend(_collect_dir(WEB_DIST, "web/dist"))
    datas.extend(_collect_dir(
        os.path.join(ROOT, "post_service", "algorithms"),
        "post_service/algorithms", exts=(".py",)))
    datas.extend(_collect_dir(
        os.path.join(ROOT, "post_service", "config"),
        "post_service/config"))

    print("  模式: {} | hidden-imports: {} | collect 任务: {} | datas: {}"
          .format("onefile" if onefile else "onedir",
                  len(hidden_imports), len(collect_alls), len(datas)))

    exe_section = (_EXE_ONEFILE if onefile else _EXE_ONEDIR).format(
        target_name=TARGET_NAME)

    spec = _SPEC_TEMPLATE.format(
        launcher=LAUNCHER.replace("\\", "\\\\"),
        root=ROOT.replace("\\", "\\\\"),
        hidden_imports=hidden_imports,
        datas=datas,
        excludes=_EXCLUDES,
        collect_alls=collect_alls,
        metadata_pkgs=_METADATA_PKGS,
        exe_section=exe_section,
    )
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(spec)


def step_pyinstaller(onefile):
    print("\n[4/5] PyInstaller 打包 ({})".format("onefile" if onefile else "onedir"))
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("  未检测到 PyInstaller, 自动 pip install ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    spec_path = os.path.join(ROOT, TARGET_NAME + ".spec")
    _write_spec(spec_path, onefile)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--workpath", BUILD,
        "--distpath", DIST,
        spec_path,
    ]
    print(">> " + " ".join(cmd))
    subprocess.check_call(cmd)


# ---------------------------------------------------------------------------
# 5) 收尾: 拷 .env / 写 start.bat / 写 README
# ---------------------------------------------------------------------------

_START_BAT = """\
@echo off
chcp 65001 >nul
title ChatCFD
echo ========================================
echo   ChatCFD - Starting Services
echo ========================================
echo.

set "ROOT=%~dp0"

if not exist "%ROOT%chatcfd.exe" (
    echo [ERROR] chatcfd.exe not found next to this script.
    pause
    exit /b 1
)

echo [1/2] Starting Post Service (port 8001)...
start "ChatCFD - PostService" "%ROOT%chatcfd.exe" post

echo      Waiting for Post Service to come up...
timeout /t 8 /nobreak >nul

echo [2/2] Starting Agent Service (port 8090)...
start "ChatCFD - Agent" "%ROOT%chatcfd.exe" agent

timeout /t 4 /nobreak >nul

echo.
echo ========================================
echo   All services started.
echo   Open: http://localhost:8001
echo ========================================
echo.

start "" "http://localhost:8001"

echo Close this window or press any key to exit.
echo (Services keep running in their own windows.)
pause >nul
"""


def step_finalize(out_dir):
    """out_dir 是 exe 所在目录 (onedir: dist/chatcfd/, onefile: dist/)。"""
    print("\n[5/5] 收尾: .env / start.bat / README.txt -> " + out_dir)

    env_src = os.path.join(ROOT, ".env")
    if not os.path.isfile(env_src):
        env_src = os.path.join(ROOT, ".env.example")
        print("  [warn] .env 不存在, 用 .env.example —— 分发前记得填真实 key")
    shutil.copyfile(env_src, os.path.join(out_dir, ".env"))

    with open(os.path.join(out_dir, "start.bat"), "w",
              encoding="ascii", newline="\r\n") as f:
        f.write(_START_BAT)

    readme_src = os.path.join(ROOT, "tools", "release_README_exe.txt")
    if os.path.isfile(readme_src):
        shutil.copyfile(readme_src, os.path.join(out_dir, "README.txt"))
    else:
        print("  [warn] tools/release_README_exe.txt 缺失, 跳过 README")


def _dir_size_mb(path):
    total = 0
    for dp, _dn, fns in os.walk(path):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total / 1024 / 1024


def main():
    onefile = "--onefile" in sys.argv
    skip_frontend = "--skip-frontend" in sys.argv

    step_frontend(skip_frontend)
    step_clean()
    step_launcher()
    step_pyinstaller(onefile)
    step_clean_spec()

    if onefile:
        out_dir = DIST
    else:
        out_dir = os.path.join(DIST, TARGET_NAME)
    step_finalize(out_dir)

    print("\n打包完成:")
    if onefile:
        exe = os.path.join(DIST, TARGET_NAME + ".exe")
        mb = os.path.getsize(exe) / 1024 / 1024 if os.path.isfile(exe) else 0
        print("  exe : {}  ({:.0f} MB)".format(exe, mb))
        print("  dist/ 同目录还有 .env / start.bat / README.txt")
        print("  分发: 把 dist/ 里这 4 个文件一起发。")
    else:
        print("  目录: {}  ({:.0f} MB)".format(out_dir, _dir_size_mb(out_dir)))
        print("  分发: 把整个 dist/chatcfd/ 文件夹打包发给用户。")
    print("  测试: 进入该目录, 双击 start.bat (或 chatcfd.exe)")
    print()
    print("[!] 若启动报缺模块, 把模块名加进 build.py 的 _BASE_HIDDEN_IMPORTS 重打。")


if __name__ == "__main__":
    main()
