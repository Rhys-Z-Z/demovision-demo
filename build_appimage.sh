#!/bin/bash
# ============================================================
# DemoVision 设备质检平台 — AppImage 打包脚本（公开演示版）
#
# 产物：DemoVision-<版本>-x86_64.AppImage（双击即开，无需 Docker / ROS / 硬件）
#
# 设计要点：
#   - 自包含 Python 3.8 运行时（解释器 + 标准库 + 动态库依赖全打进 AppDir），
#     目标机不需要装 Python / pip / node / docker。
#   - 前端用已构建好的 frontend/dist，由后端直接伺服，不需要 node。
#   - 演示数据不打包：首次运行自动播种到 $HOME/demovision_data（AppImage 挂载只读）。
#   - 图标使用项目根目录的 demo_icon.png（256x256）。
#
# 用法：
#   cd demovision-demo
#   ./build_appimage.sh              # 默认版本 1.0
#   VERSION=1.1 ./build_appimage.sh  # 自定义版本
#
# 依赖（仅开发机打包时需要）：mksquashfs（squashfs-tools）、本机 Python 3.8
# ============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

APP_NAME="DemoVision"                      # AppImage 文件名前缀
APP_TITLE="DemoVision 设备质检平台"          # .desktop 显示名
VERSION="${VERSION:-1.0}"
ICON_SRC="$PROJECT_DIR/demo_icon.png"
ICON_NAME="demo_icon"                      # .desktop 的 Icon= 值，须与 AppDir 中图标文件名一致
OUT_FILE="$PROJECT_DIR/${APP_NAME}-${VERSION}-x86_64.AppImage"
APPDIR="$PROJECT_DIR/.appimage-build/AppDir"
STAGE="$PROJECT_DIR/.appimage-build"
PY_VER="3.8"
SYS_PY="/usr/bin/python3.8"

# appimagetool 查找顺序：项目 .appimage/ → 同级项目已有副本 → 下载（走 GitHub 镜像）
APPIMAGETOOL=""
for c in "$PROJECT_DIR/.appimage/appimagetool" \
         "$PROJECT_DIR/../生产检测（web） (copy)/.appimage/appimagetool" \
         "$PROJECT_DIR/../生产检测（web）/.appimage/appimagetool"; do
  [ -s "$c" ] && { APPIMAGETOOL="$c"; break; }
done

info() { echo -e "\033[1;36m[打包]\033[0m $*"; }
warn() { echo -e "\033[1;33m[打包]\033[0m $*"; }
die()  { echo -e "\033[1;31m[打包]\033[0m $*" >&2; exit 1; }

# ---------- 0. 前置检查 ----------
info "0/8 前置检查"
[ -f "$ICON_SRC" ]                      || die "缺少图标: $ICON_SRC"
[ -f frontend/dist/index.html ]         || die "缺少前端构建产物 frontend/dist/index.html，请先 cd frontend && npm run build"
[ -d backend/pipdeps ]                  || die "缺少后端依赖 backend/pipdeps，请先跑一次 ./start.sh 安装依赖"
[ -d backend/app ]                      || die "缺少后端代码 backend/app"
[ -x "$SYS_PY" ]                        || die "缺少系统 Python: $SYS_PY（打包需要它作为内嵌运行时）"
command -v mksquashfs >/dev/null        || die "缺少 mksquashfs，请安装: sudo apt install squashfs-tools"

if [ -z "$APPIMAGETOOL" ]; then
  info "本地无 appimagetool，尝试下载..."
  mkdir -p "$PROJECT_DIR/.appimage"
  for u in \
    "https://ghfast.top/https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
    "https://ghproxy.net/https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" ; do
    echo "  尝试: $u"
    timeout 90 wget -q --timeout=80 "$u" -O "$PROJECT_DIR/.appimage/appimagetool" && break || rm -f "$PROJECT_DIR/.appimage/appimagetool"
  done
  [ -s "$PROJECT_DIR/.appimage/appimagetool" ] || die "appimagetool 下载失败，请手动放到 $PROJECT_DIR/.appimage/appimagetool"
  APPIMAGETOOL="$PROJECT_DIR/.appimage/appimagetool"
fi
chmod +x "$APPIMAGETOOL"
info "appimagetool: $APPIMAGETOOL"

# ---------- 1. 清理 + 建目录 ----------
info "1/8 初始化 AppDir"
rm -rf "$STAGE"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# ---------- 2. 内嵌 Python 运行时 ----------
info "2/8 拷贝 Python ${PY_VER} 运行时（解释器 + 标准库）"
cp -a "$SYS_PY" "$APPDIR/usr/bin/python3.8"
ln -sf python3.8 "$APPDIR/usr/bin/python3"

# 标准库：整树复制后剔除用不到的大块（tkinter/test/idlelib 等），显著减小体积
cp -a "/usr/lib/python${PY_VER}" "$APPDIR/usr/lib/python3.8"
for junk in test tests idlelib tkinter lib2to3 tumbleweed ensurepip distutils/site-packages; do
  rm -rf "$APPDIR/usr/lib/python3.8/$junk"
done
find "$APPDIR/usr/lib/python3.8" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
# tk 相关扩展（后端不使用图形界面）
rm -f "$APPDIR/usr/lib/python3.8/lib-dynload"/_tkinter*.so \
      "$APPDIR/usr/lib/python3.8/lib-dynload"/_test*.so 2>/dev/null || true

# ---------- 3. 动态库依赖闭包 ----------
info "3/8 收集动态库依赖（解释器扩展 + pipdeps 二进制）"
DEPS_TMP="$STAGE/so_deps.txt"
python3 - "$APPDIR/usr/lib/python3.8/lib-dynload" "$PROJECT_DIR/backend/pipdeps" > "$DEPS_TMP" <<'PY'
import glob, os, subprocess, sys

def ldd(path):
    try:
        out = subprocess.run(["ldd", path], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return []
    libs = []
    for line in out.splitlines():
        if "=>" in line:
            p = line.split("=>", 1)[1].strip().split(" ")[0]
            if p.startswith("/"):
                libs.append(p)
    return libs

roots = []
for d in sys.argv[1:]:
    roots += glob.glob(os.path.join(d, "*.so"))
    roots += glob.glob(os.path.join(d, "*", "*.so"))

# 闭包展开（含二级依赖，如 libssl → libcrypto）
seen, queue = set(), list(roots)
while queue:
    p = queue.pop()
    if p in seen:
        continue
    seen.add(p)
    for l in ldd(p):
        if l not in seen:
            queue.append(l)

# 排除 glibc 核心 / C++ 运行时（宿主必有，且混入会引发 ABI 冲突）
CORE = ("libc.so", "libm.so", "libpthread", "libdl.so", "libutil.so", "librt.so",
        "ld-linux", "libgcc_s", "libstdc++", "linux-vdso")
pip_root = os.path.abspath(sys.argv[2])
for p in sorted(seen):
    base = os.path.basename(p)
    if any(base.startswith(c) for c in CORE):
        continue
    # pipdeps 内部自带的库（Pillow 的 pillow.libs 等）由其 RPATH 解析，无需外带
    if os.path.abspath(p).startswith(pip_root):
        continue
    print(p)
PY
DEPS=$(sort -u "$DEPS_TMP")
LIB_COUNT=$(printf '%s\n' "$DEPS" | grep -c . || true)
info "  需要外带 ${LIB_COUNT} 个系统库"
while read -r lib; do
  [ -n "$lib" ] && [ -f "$lib" ] && cp -a "$lib" "$APPDIR/usr/lib/"
done <<< "$DEPS"

# ---------- 4. 应用本体 ----------
info "4/8 拷贝应用本体（backend/pipdeps + frontend/dist + scripts）"
mkdir -p "$APPDIR/usr/app"
cp -a backend "$APPDIR/usr/app/backend"
cp -a frontend "$APPDIR/usr/app/frontend"
cp -a scripts "$APPDIR/usr/app/scripts"
[ -d imu_tool ] && cp -a imu_tool "$APPDIR/usr/app/imu_tool"
cp -a README.md "$APPDIR/usr/app/README.md" 2>/dev/null || true
# 前端只保留构建产物与源码说明：node_modules 绝不打包
rm -rf "$APPDIR/usr/app/frontend/node_modules"
# 演示数据不入包（首次运行播种到宿主目录）
rm -rf "$APPDIR/usr/app/backend/demo_data"
# 打包机残留：运行时数据库 / 缓存 / 测试产物
rm -f  "$APPDIR/usr/app/backend"/*.db "$APPDIR/usr/app/backend"/*.log 2>/dev/null || true
rm -rf "$APPDIR/usr/app/backend/.pytest_cache" "$APPDIR/usr/app/backend/tests" 2>/dev/null || true

# ---------- 5. AppRun ----------
info "5/8 生成 AppRun 入口"
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
# DemoVision 设备质检平台 — AppImage 运行时入口
# 双击后：启动内置后端（模拟数据模式）→ 打开浏览器 → 保持运行，Ctrl+C / 关闭终端即退出
set -u
HERE="$(dirname "$(readlink -f "$0")")"
APP_ROOT="$HERE/usr/app"
# 注意：$0 在 AppImage 内部是挂载点里的 AppRun，不能用它重入；
# APPIMAGE 是 AppImage 文件本身（AppImage 规范提供），但可能是相对路径 → 转成绝对路径
SELF="${APPIMAGE:-$0}"
case "$SELF" in /*) ;; *) SELF="$(pwd)/$SELF" ;; esac

# 双击（无终端）时自动在终端里运行，便于看日志与退出；DEMOVISION_APPIMAGE_INTERNAL 防止递归
# 判据：stdin 与 stdout 都不是 tty（真正的双击）才包装；`./x.AppImage > log` 这类重定向不干扰
if [ ! -t 0 ] && [ ! -t 1 ] && [ -z "${DEMOVISION_APPIMAGE_INTERNAL:-}" ]; then
  for term in gnome-terminal konsole xfce4-terminal x-terminal-emulator xterm; do
    if command -v "$term" >/dev/null 2>&1; then
      export DEMOVISION_APPIMAGE_INTERNAL=1
      case "$term" in
        gnome-terminal) exec "$term" -- bash -c "\"$SELF\"; echo; read -r -p '按回车关闭窗口...'" ;;
        *)              exec "$term" -e "$SELF" ;;
      esac
    fi
  done
  # 无终端程序：退回纯后台模式（日志落盘）
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONHOME="$HERE/usr"
export PYTHONPATH="$APP_ROOT/backend/pipdeps"
export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export DEMOVISION_DEMO_MODE="${DEMOVISION_DEMO_MODE:-1}"
export DEMOVISION_APP_DIR="$APP_ROOT"
export DEMOVISION_DATA_DIR="${DEMOVISION_DATA_DIR:-$HOME/demovision_data}"
export DEMOVISION_DB_DIR="${DEMOVISION_DB_DIR:-$DEMOVISION_DATA_DIR}"
mkdir -p "$DEMOVISION_DATA_DIR" 2>/dev/null || true
LOG="$DEMOVISION_DATA_DIR/appimage.log"

# 端口：默认 8010，被占用则顺延
PORT="${PORT:-8010}"
while [ "$PORT" -le 8099 ] && (echo > "/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; do
  PORT=$((PORT+1))
done

echo "==============================================="
echo " DemoVision 设备质检平台（公开演示版）"
echo " 模式    : Demo 模拟数据（无需 ROS / SDK / 硬件）"
echo " 数据目录: $DEMOVISION_DATA_DIR"
echo " 访问地址: http://127.0.0.1:$PORT/"
echo " 日志    : $LOG"
echo " 退出    : 按 Ctrl+C"
echo "==============================================="

cd "$APP_ROOT/backend" || exit 1
"$HERE/usr/bin/python3.8" -m uvicorn app.main:app \
  --host 127.0.0.1 --port "$PORT" --access-log >>"$LOG" 2>&1 &
BACKEND_PID=$!

cleanup() {
  echo
  echo "正在停止 DemoVision 服务..."
  kill "$BACKEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
  echo "已退出。"
}
trap cleanup EXIT INT TERM

# 等待后端就绪（最多 30s）
READY=0
for _ in $(seq 1 120); do
  if (echo > "/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then READY=1; break; fi
  kill -0 "$BACKEND_PID" 2>/dev/null || break
  sleep 0.25
done

if [ "$READY" = "1" ]; then
  echo "服务已就绪，正在打开浏览器..."
  if command -v xdg-open >/dev/null 2>&1; then
    (xdg-open "http://127.0.0.1:$PORT/" >/dev/null 2>&1 &)
  else
    echo "未找到 xdg-open，请手动打开: http://127.0.0.1:$PORT/"
  fi
else
  echo "❌ 后端启动失败，日志尾部如下："
  tail -n 20 "$LOG" 2>/dev/null
  echo
  if [ -t 1 ]; then read -p "按回车退出..."; fi
  exit 1
fi

wait "$BACKEND_PID"
EOF
chmod +x "$APPDIR/AppRun"

# ---------- 6. .desktop ----------
info "6/8 生成 .desktop"
cat > "$APPDIR/$ICON_NAME.desktop" << EOF
[Desktop Entry]
Type=Application
Name=$APP_TITLE
Name[en]=DemoVision Device QC Platform
Comment=产线检测 / SLAM 监控 / IMU 校准 — 公开演示版（模拟数据，无需硬件）
Exec=AppRun
Icon=$ICON_NAME
Terminal=true
Categories=Development;Utility;Engineering;
Keywords=demo;qc;slam;检测;质检;
StartupNotify=true
EOF
# appimagetool 要求根目录存在与 APP_NAME 同名的 desktop
cp "$APPDIR/$ICON_NAME.desktop" "$APPDIR/$APP_NAME.desktop"
cp "$APPDIR/$ICON_NAME.desktop" "$APPDIR/usr/share/applications/$ICON_NAME.desktop"

# ---------- 7. 图标 ----------
info "7/8 放置图标（$ICON_SRC）"
cp "$ICON_SRC" "$APPDIR/$ICON_NAME.png"
cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/$ICON_NAME.png"
ln -sf "$ICON_NAME.png" "$APPDIR/.DirIcon"

# ---------- 8. 打包 ----------
info "8/8 生成 AppImage"
ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$OUT_FILE"

rm -rf "$STAGE/AppDir" "$DEPS_TMP" 2>/dev/null || true

echo
info "完成！"
ls -lh "$OUT_FILE"
echo
echo "运行方式："
echo "  双击 $(basename "$OUT_FILE")   （或在终端 ./$(basename "$OUT_FILE")）"
echo "  首次启动会在 \$HOME/demovision_data 自动播种演示数据，浏览器自动打开 http://127.0.0.1:8010/"
echo "  自定义：PORT=9010 ./$(basename "$OUT_FILE")   /   DEMOVISION_DATA_DIR=/data ./$(basename "$OUT_FILE")"
