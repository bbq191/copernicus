#!/usr/bin/env bash
# Copernicus 一键部署：服务用户 → 后端环境 → 前端构建 → systemd → Nginx → 健康检查
#
# 不包含（需按机器情况手工准备，见 docs/intro/deployment.md）：
#   NVIDIA 驱动 / CUDA、ffmpeg、uv、Ollama 及 LLM 模型、Node.js、Nginx 本身
#
# 可重复执行：已存在的用户、虚拟环境、.env、已安装的依赖都会被跳过或原样保留。

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SERVER_NAME="${SERVER_NAME:-_}"
TORCH_VARIANT="${TORCH_VARIANT:-}"   # 对应 backend/pyproject.toml 中的 extra：cpu / cu126 / cu130；为空时见 resolve_torch_variant
PYTHON="${PYTHON:-}"
UV="${UV:-}"
VENV_BACKED_UP=0
VENV_OK_MARKER=".copernicus-install-ok"   # 写在 .venv 内：同步与打补丁都成功的环境才有
SKIP_FRONTEND=0
WITH_NGINX=1
START_SERVICE=1
DOWNLOAD_MODELS=0
OPEN_FIREWALL=0
USER_CREATED="${USER_CREATED:-0}"
FIREWALL_OPENED="${FIREWALL_OPENED:-0}"

usage() {
    cat <<USAGE
用法：sudo deploy/install.sh [选项]

  --user NAME         服务运行用户（默认 ${SERVICE_USER}，不存在则创建）
  --app-dir DIR       代码目录（默认 ${APP_DIR}）
  --data-dir DIR      数据目录，上传文件放在 DIR/uploads（默认 ${DATA_DIR}）
  --web-root DIR      前端发布目录（默认 ${WEB_ROOT}）
  --server-name NAME  Nginx server_name / 访问域名或 IP（默认 _，匹配任意）
  --port N            后端监听端口，仅本机回环（默认 ${PORT}）
  --python PATH       Python 3.12 解释器（默认自动查找）
  --uv PATH           uv 可执行文件（默认自动查找；服务用户须能执行）
  --torch VARIANT     PyTorch 变体：cpu / cu126 / cu130（cu126 需驱动 >= 525，cu130 需驱动 >= 580）；
                      不指定时沿用上次记录，没有记录则按现有 venv 里的 torch 推断，全新安装用 cu126
  --cpu               等同 --torch cpu（无 NVIDIA GPU 时使用）
  --download-models   联网预下载 ASR 模型
  --skip-frontend     不构建前端
  --no-nginx          不配置 Nginx
  --no-start          只安装，不启动服务
  --open-firewall     用 firewalld 放行 http 服务
  --dry-run           只打印将执行的操作，不做任何改动
  -y, --yes           不询问确认
  -h, --help          显示本帮助
USAGE
}

parse_args() {
    while (($#)); do
        case "$1" in
            --user)            SERVICE_USER="${2:?}"; shift 2 ;;
            --app-dir)         APP_DIR="${2:?}"; shift 2 ;;
            --data-dir)        DATA_DIR="${2:?}"; shift 2 ;;
            --web-root)        WEB_ROOT="${2:?}"; shift 2 ;;
            --server-name)     SERVER_NAME="${2:?}"; shift 2 ;;
            --port)            PORT="${2:?}"; shift 2 ;;
            --python)          PYTHON="${2:?}"; shift 2 ;;
            --uv)              UV="${2:?}"; shift 2 ;;
            --torch)           TORCH_VARIANT="${2:?}"; shift 2 ;;
            --cpu)             TORCH_VARIANT=cpu; shift ;;
            --torch-index)     die "--torch-index 已移除：依赖改由 uv.lock 锁定，请用 --torch cpu|cu126|cu130" ;;
            --download-models) DOWNLOAD_MODELS=1; shift ;;
            --skip-frontend)   SKIP_FRONTEND=1; shift ;;
            --no-nginx)        WITH_NGINX=0; shift ;;
            --no-start)        START_SERVICE=0; shift ;;
            --open-firewall)   OPEN_FIREWALL=1; shift ;;
            --dry-run)         DRY_RUN=1; shift ;;
            -y|--yes)          ASSUME_YES=1; shift ;;
            -h|--help)         usage; exit 0 ;;
            *) usage >&2; die "未知选项：$1" ;;
        esac
    done
    [[ -z $TORCH_VARIANT || $TORCH_VARIANT =~ ^(cpu|cu126|cu130)$ ]] || die "非法的 --torch：$TORCH_VARIANT（可选 cpu / cu126 / cu130）"
    [[ $PORT =~ ^[0-9]+$ && $PORT -ge 1 && $PORT -le 65535 ]] || die "--port 必须是 1-65535 之间的数字"
    [[ $SERVICE_USER =~ ^[a-z_][a-z0-9_-]*$ ]] || die "非法的用户名：$SERVICE_USER"
    # "_" 是 nginx server_name 的通配写法；否则只接受主机名/IP 合法字符，
    # 避免拼进 nginx 配置与 CORS_ORIGINS JSON 字符串时因特殊字符破坏格式
    [[ $SERVER_NAME == _ || $SERVER_NAME =~ ^[A-Za-z0-9.-]+$ ]] || die "非法的 --server-name：$SERVER_NAME"
    finalize_paths
}

# ------------------------------------------------------------------ 步骤 --

find_python() {
    local candidate
    for candidate in "$PYTHON" "$(command -v python3.12 || true)" \
        /usr/local/bin/python3.12 /home/*/.pyenv/versions/3.12*/bin/python; do
        [[ -n $candidate && -x $candidate ]] && { echo "$candidate"; return 0; }
    done
    return 1
}

# 官方安装脚本默认装到执行者的 ~/.local/bin；root 的 home 服务用户进不去，所以优先找系统路径
find_uv() {
    local candidate
    for candidate in "$UV" "$(command -v uv || true)" /usr/local/bin/uv /usr/bin/uv; do
        [[ -n $candidate && -x $candidate ]] && { echo "$candidate"; return 0; }
    done
    return 1
}

# 旧版脚本不记录 torch 变体，生产 venv 里的 torch 可能是手工换装的；
# 不能静默套用默认值，否则重跑会把现有 CUDA 构建换掉
resolve_torch_variant() {
    [[ -n $TORCH_VARIANT ]] && return 0
    local venv_python="$APP_DIR/backend/.venv/bin/python" cuda
    if [[ ! -x $venv_python ]] || ! cuda="$("$venv_python" -c 'import torch; print(torch.version.cuda or "cpu")' 2>/dev/null)"; then
        TORCH_VARIANT=cu126
        log "未找到已安装的 torch，PyTorch 变体使用默认 cu126"
        return 0
    fi
    case "$cuda" in
        cpu)  TORCH_VARIANT=cpu ;;
        12.6) TORCH_VARIANT=cu126 ;;
        13.0) TORCH_VARIANT=cu130 ;;
        *) die "现有 venv 的 torch 是 CUDA $cuda 构建，无法对应到 cpu / cu126 / cu130，请用 --torch 显式指定" ;;
    esac
    log "按现有 venv 的 torch（$cuda 构建）推断 PyTorch 变体：$TORCH_VARIANT"
}

preflight() {
    step "环境检查"
    have systemctl || die "需要 systemd"
    have ffmpeg    || die "未找到 ffmpeg（音视频处理必需），请先安装"
    [[ -f $APP_DIR/backend/pyproject.toml ]] || die "$APP_DIR 不是 Copernicus 代码目录"

    PYTHON="$(find_python)" || die "未找到 Python 3.12，请安装后用 --python 指定"
    log "Python：$PYTHON"
    UV="$(find_uv)" || die "未找到 uv，请安装到系统路径后重试（或用 --uv 指定）：
  curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh"
    resolve_torch_variant
    log "uv：$UV（$("$UV" --version)）  PyTorch 变体：$TORCH_VARIANT"

    if ((!SKIP_FRONTEND)); then
        { have node && have npm; } || die "构建前端需要 Node.js（>=20）与 npm；也可加 --skip-frontend"
        local node_major
        node_major="$(node -p 'process.versions.node.split(".")[0]')"
        ((node_major >= 20)) || die "Node.js 版本过低（$(node -v)），需要 >=20"
    fi
    ((WITH_NGINX)) && ! have nginx && { warn "未安装 nginx，跳过反向代理配置"; WITH_NGINX=0; }

    if [[ $TORCH_VARIANT != cpu ]] && ! have nvidia-smi; then
        warn "未检测到 nvidia-smi；没有 GPU 请加 --cpu，否则 ASR 无法使用 CUDA"
    fi
    if have getenforce && [[ $(getenforce) == Enforcing ]]; then
        warn "SELinux 处于 Enforcing：前端目录将尝试 restorecon；若仍出现 403/502 请检查审计日志"
    fi
}

ensure_user() {
    step "服务用户与目录"
    if id "$SERVICE_USER" >/dev/null 2>&1; then
        log "用户 $SERVICE_USER 已存在"
    else
        run useradd --system --create-home --home-dir "/var/lib/$SERVICE_USER" \
            --shell /sbin/nologin "$SERVICE_USER"
        USER_CREATED=1
    fi

    local backend="$APP_DIR/backend" frontend="$APP_DIR/frontend"
    # 数据目录存放用户上传的原始音视频与任务结果，收紧到仅本用户可读写，
    # 避免同机其他本地账户（默认权限下）能够列出/读取这些审核素材
    run install -d -m 750 -o "$SERVICE_USER" -g "$SERVICE_USER" \
        "$DATA_DIR" "$DATA_DIR/uploads"
    run install -d -o "$SERVICE_USER" -g "$SERVICE_USER" \
        "$backend/.venv" "$backend/models"
    ((SKIP_FRONTEND)) || run install -d -o "$SERVICE_USER" -g "$SERVICE_USER" \
        "$frontend/node_modules" "$frontend/dist"
}

ensure_env_file() {
    local env_file="$APP_DIR/backend/.env" template
    if [[ -f $env_file ]]; then
        log "保留已有 $env_file"
        return 0
    fi
    for template in "$APP_DIR/backend/.env.prod" "$APP_DIR/backend/.env.example"; do
        [[ -f $template ]] && break
    done
    [[ -f $template ]] || die "未找到 .env 模板（$APP_DIR/backend/.env.prod 或 .env.example）"
    log "由 $(basename "$template") 生成 .env"
    run install -m 640 -o "$SERVICE_USER" -g "$SERVICE_USER" "$template" "$env_file"
    set_env_key "$env_file" UPLOAD_DIR "$DATA_DIR/uploads"
    # 同源部署（Nginx 统一入口）无需 CORS；指定域名时放行该来源
    if [[ $SERVER_NAME == _ ]]; then
        set_env_key "$env_file" CORS_ORIGINS '[]'
    else
        set_env_key "$env_file" CORS_ORIGINS "[\"http://$SERVER_NAME\"]"
    fi
}

# 整行替换 KEY=VALUE（行内注释随之丢弃）；不存在则追加
set_env_key() {
    local file="$1" key="$2" value="$3" escaped
    escaped="$(printf '%s' "$value" | sed -e 's/[\\&|]/\\&/g')"
    if ((DRY_RUN)); then
        echo "  [dry-run] $file: $key=$value"
    elif grep -q "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${escaped}|" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >>"$file"
    fi
}

setup_backend() {
    step "后端 Python 环境"
    local backend="$APP_DIR/backend" venv="$APP_DIR/backend/.venv"

    if ((!DRY_RUN)); then
        runuser -u "$SERVICE_USER" -- "$PYTHON" -V >/dev/null 2>&1 \
            || die "用户 $SERVICE_USER 无法执行 $PYTHON（pyenv 位于他人 home 时权限不足），请用 --python 指定其可访问的解释器"
        runuser -u "$SERVICE_USER" -- "$UV" --version >/dev/null 2>&1 \
            || die "用户 $SERVICE_USER 无法执行 $UV，请把 uv 装到 /usr/local/bin 或用 --uv 指定"
    fi

    # 同步会原地替换 torch/CUDA 动态库，运行中的服务之后再按需导入（如 ChatTTS）可能崩溃，先停掉；
    # install_service 会重新启动
    if ((!DRY_RUN)) && systemctl is-active --quiet "$SERVICE_NAME"; then
        log "停止 $SERVICE_NAME 以更新 Python 环境"
        systemctl stop "$SERVICE_NAME"
    fi

    # 同步会按 uv.lock 增删包（torch 可能跨大版本），先留一份可回退的旧环境。
    # 只备份确认完好的环境：$VENV_OK_MARKER 在同步和打补丁都成功后才写入。上次失败留下的
    # 半成品没有标记，此时保留已有的 .venv.bak，不能拿坏环境覆盖唯一的好备份。
    # 从 pip 时代升级的首次运行没有标记也没有备份，照常备份。
    # --reflink=auto：XFS/btrfs 上只复制元数据，几乎不占额外空间
    if [[ -x $venv/bin/python ]]; then
        if [[ -f $venv/$VENV_OK_MARKER || ! -d $venv.bak ]]; then
            run rm -rf "$venv.bak"
            run cp -a --reflink=auto "$venv" "$venv.bak"
        else
            warn "当前 .venv 是上次未完成的安装，保留已有备份 $venv.bak"
        fi
    fi
    [[ -d $venv.bak ]] && VENV_BACKED_UP=1
    run rm -f "$venv/$VENV_OK_MARKER"

    # venv 仍由 python -m venv 创建，uv 只往里同步包：uv 认为解释器不符（如 .python-version
    # 写的补丁版本与本机不同）时会删掉整个 .venv 重建，而服务用户对 backend/ 没有写权限，
    # 会删到一半失败、留下空环境。--python 指向 venv 自身的解释器即可避免重建
    [[ -x $venv/bin/python ]] || run_as_service_user "$PYTHON" -m venv "$venv"

    # --frozen 严格按 uv.lock 安装，不重新解析；torch 变体由 extra 决定，tts 为 ChatTTS（音频重塑）
    # UV_PROJECT_ENVIRONMENT 显式指定环境位置，不依赖当前工作目录
    if ! run_as_service_user env "UV_PROJECT_ENVIRONMENT=$venv" "UV_PYTHON_DOWNLOADS=never" \
        "$UV" sync --frozen --project "$backend" --python "$venv/bin/python" \
        --extra "$TORCH_VARIANT" --extra tts; then
        rollback_hint
        die "uv sync 失败，见上方输出"
    fi

    # uv sync 重装 funasr 时会覆盖补丁，所以每次同步后都要重打
    log "应用 FunASR 补丁（置信度过滤依赖它，缺失会使纠错耗时增加数十倍）"
    if ! run_as_service_user "$venv/bin/python" "$backend/scripts/patch_funasr.py"; then
        rollback_hint
        die "FunASR 补丁失败，见上方输出"
    fi
    run_as_service_user touch "$venv/$VENV_OK_MARKER"
}

check_models() {
    step "模型文件"
    local models="$APP_DIR/backend/models"
    if ((DOWNLOAD_MODELS)); then
        run_as_service_user env "MODELSCOPE_CACHE=$models/funasr" \
            "$APP_DIR/backend/.venv/bin/python" "$APP_DIR/backend/scripts/download_models.py"
    fi
    ((DRY_RUN)) && return 0
    [[ -n $(ls -A "$models/funasr/models/iic" 2>/dev/null) ]] \
        || warn "缺少 ASR 模型（$models/funasr/models/iic）：加 --download-models 联网下载，或离线拷入"
    [[ -f $models/yolo/yolov8n-face.pt ]] \
        || warn "缺少人脸检测模型 $models/yolo/yolov8n-face.pt（合规审核的人脸检测不可用）"
    [[ -d $models/chattts/asset ]] \
        || warn "缺少 ChatTTS 模型 $models/chattts/（音频合成不可用）"
    return 0
}

build_frontend() {
    ((SKIP_FRONTEND)) && return 0
    step "前端构建与发布"
    local frontend="$APP_DIR/frontend"
    # npm ci 严格按 package-lock.json 安装，比 npm install 更快且结果可复现
    run_as_service_user npm --prefix "$frontend" ci --no-audit --no-fund
    run_as_service_user npm --prefix "$frontend" run build

    # 复制到 Nginx 专用目录：应用目录无需对 nginx 开放，也避免 SELinux 标签问题。
    # 先写临时目录再改名，切换瞬间完成，用户不会遇到半成品
    run rm -rf "$WEB_ROOT.new"
    run cp -a "$frontend/dist" "$WEB_ROOT.new"
    run chmod -R a+rX "$WEB_ROOT.new"
    run rm -rf "$WEB_ROOT.old"
    [[ -d $WEB_ROOT ]] && run mv "$WEB_ROOT" "$WEB_ROOT.old"
    run mv "$WEB_ROOT.new" "$WEB_ROOT"
    run rm -rf "$WEB_ROOT.old"
    if have restorecon; then
        run restorecon -R "$WEB_ROOT" || true
    fi
}

install_service() {
    step "systemd 服务"
    render_template "$REPO_DIR/deploy/templates/copernicus-backend.service.in" "$UNIT_FILE"
    if have systemd-analyze && ((!DRY_RUN)); then
        local verify_output
        verify_output="$(systemd-analyze verify "$UNIT_FILE" 2>&1 | grep -v "ollama.service" || true)"
        [[ -z $verify_output ]] || warn "systemd-analyze verify 发现问题（服务仍会继续安装/启动，请核实）：
$verify_output"
    fi
    run systemctl daemon-reload
    run systemctl enable "$SERVICE_NAME"
    ((START_SERVICE)) && run systemctl restart "$SERVICE_NAME"
    return 0
}

install_nginx() {
    ((WITH_NGINX)) || return 0
    step "Nginx 反向代理"
    local backup=""
    [[ -f $NGINX_CONF ]] && { backup="$NGINX_CONF.bak"; run cp -a "$NGINX_CONF" "$backup"; }
    render_template "$REPO_DIR/deploy/templates/copernicus.nginx.conf.in" "$NGINX_CONF"
    if ! reload_nginx; then
        warn "nginx 配置校验失败，已回滚"
        if [[ -n $backup ]]; then mv "$backup" "$NGINX_CONF"; else rm -f "$NGINX_CONF"; fi
        die "请检查 nginx -t 的输出（可能与已有站点冲突：同一端口的 server_name/default_server）"
    fi
    if ((OPEN_FIREWALL)) && have firewall-cmd && firewall-cmd --state >/dev/null 2>&1; then
        run firewall-cmd --permanent --add-service=http
        run firewall-cmd --reload
        FIREWALL_OPENED=1
    fi
}

wait_healthy() {
    ((START_SERVICE)) || return 0
    ((DRY_RUN)) && { echo "  [dry-run] 等待 /api/v1/health/live"; return 0; }
    step "等待服务就绪（加载 ASR 模型约需 30-60 秒）"
    local i
    for ((i = 0; i < 90; i++)); do
        if curl -fsS "http://127.0.0.1:$PORT/api/v1/health/live" >/dev/null 2>&1; then
            log "后端已就绪"
            return 0
        fi
        systemctl is-active --quiet "$SERVICE_NAME" || break
        sleep 2
    done
    warn "服务未在预期时间内就绪，请查看：journalctl -u $SERVICE_NAME -n 100"
    return 1
}

summary() {
    step "完成"
    cat <<SUMMARY
服务用户：$SERVICE_USER      代码目录：$APP_DIR
数据目录：$DATA_DIR/uploads  前端目录：$WEB_ROOT

后续：
  · 组件详情：curl http://127.0.0.1:$PORT/api/v1/health
  · 查看日志：journalctl -u $SERVICE_NAME -f
  · LLM：确认 Ollama 在运行且已拉取 .env 中 LLM_MODEL_NAME 指定的模型
  · 卸载：sudo deploy/uninstall.sh
SUMMARY
    rollback_hint
}

rollback_hint() {
    ((VENV_BACKED_UP)) || return 0
    local venv="$APP_DIR/backend/.venv"
    cat <<ROLLBACK
  · 旧 Python 环境已备份到 $venv.bak；新环境有问题时回退：
      sudo systemctl stop $SERVICE_NAME
      sudo rm -rf $venv && sudo mv $venv.bak $venv
      sudo systemctl start $SERVICE_NAME
    确认无误后可删除备份：sudo rm -rf $venv.bak
ROLLBACK
}

main() {
    load_state
    parse_args "$@"
    require_root
    ((DRY_RUN)) && warn "dry-run：不会做任何改动"

    preflight
    ensure_user
    save_state          # 尽快落盘 USER_CREATED：后面任一步骤中断退出，uninstall.sh 仍能准确判断用户是否由本次安装创建
    ensure_env_file
    setup_backend
    check_models
    build_frontend
    install_service
    install_nginx
    save_state          # 防火墙放行结果在 install_nginx 之后才确定
    local healthy=1
    wait_healthy || healthy=0
    summary
    ((healthy)) || exit 1
}

main "$@"
