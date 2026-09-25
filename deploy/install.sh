#!/usr/bin/env bash
# Copernicus 一键部署：服务用户 → 后端环境 → 前端构建 → systemd → Nginx → 健康检查
#
# 不包含（需按机器情况手工准备，见 docs/intro/deployment.md）：
#   NVIDIA 驱动 / CUDA、ffmpeg、Ollama 及 LLM 模型、Node.js、Nginx 本身
#
# 可重复执行：已存在的用户、虚拟环境、.env、已安装的依赖都会被跳过或原样保留。

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SERVER_NAME="${SERVER_NAME:-_}"
TORCH_INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/cu121}"
PYTHON="${PYTHON:-}"
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
  --cpu               安装 CPU 版 PyTorch（无 NVIDIA GPU 时使用）
  --torch-index URL   PyTorch 下载源（默认 CUDA 12.1）
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
            --cpu)             TORCH_INDEX="https://download.pytorch.org/whl/cpu"; shift ;;
            --torch-index)     TORCH_INDEX="${2:?}"; shift 2 ;;
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
    [[ $PORT =~ ^[0-9]+$ ]] || die "--port 必须是数字"
    [[ $SERVICE_USER =~ ^[a-z_][a-z0-9_-]*$ ]] || die "非法的用户名：$SERVICE_USER"
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

preflight() {
    step "环境检查"
    have systemctl || die "需要 systemd"
    have ffmpeg    || die "未找到 ffmpeg（音视频处理必需），请先安装"
    [[ -f $APP_DIR/backend/pyproject.toml ]] || die "$APP_DIR 不是 Copernicus 代码目录"

    PYTHON="$(find_python)" || die "未找到 Python 3.12，请安装后用 --python 指定"
    log "Python：$PYTHON"

    if ((!SKIP_FRONTEND)); then
        { have node && have npm; } || die "构建前端需要 Node.js（>=20）与 npm；也可加 --skip-frontend"
        local node_major
        node_major="$(node -p 'process.versions.node.split(".")[0]')"
        ((node_major >= 20)) || die "Node.js 版本过低（$(node -v)），需要 >=20"
    fi
    ((WITH_NGINX)) && ! have nginx && { warn "未安装 nginx，跳过反向代理配置"; WITH_NGINX=0; }

    if [[ $TORCH_INDEX != */cpu ]] && ! have nvidia-smi; then
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
    run install -d -o "$SERVICE_USER" -g "$SERVICE_USER" \
        "$DATA_DIR" "$DATA_DIR/uploads" "$backend/.venv" "$backend/models"
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
    local backend="$APP_DIR/backend" venv_python="$APP_DIR/backend/.venv/bin/python"

    ((DRY_RUN)) || runuser -u "$SERVICE_USER" -- "$PYTHON" -V >/dev/null 2>&1 \
        || die "用户 $SERVICE_USER 无法执行 $PYTHON（pyenv 位于他人 home 时权限不足），请用 --python 指定其可访问的解释器"

    [[ -x $venv_python ]] || run_as_service_user "$PYTHON" -m venv "$backend/.venv"
    run_as_service_user "$venv_python" -m pip install --quiet --upgrade pip

    # torch/torchvision/torchaudio 必须先按目标 CUDA 版本从专用源安装：
    # 之后 pip install -e . 看到版本已满足就不会再从 PyPI 换成别的构建
    if ((!DRY_RUN)) && "$venv_python" -c 'import torch, torchvision, torchaudio' 2>/dev/null; then
        log "PyTorch 已安装，跳过"
    else
        run_as_service_user "$venv_python" -m pip install torch torchvision torchaudio --index-url "$TORCH_INDEX"
    fi
    run_as_service_user "$venv_python" -m pip install -e "$backend"

    log "应用 FunASR 补丁（置信度过滤依赖它，缺失会使纠错耗时增加数十倍）"
    run_as_service_user "$venv_python" "$backend/scripts/patch_funasr.py"
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
    have restorecon && run restorecon -R "$WEB_ROOT" || true
}

install_service() {
    step "systemd 服务"
    render_template "$REPO_DIR/deploy/templates/copernicus-backend.service.in" "$UNIT_FILE"
    if have systemd-analyze && ((!DRY_RUN)); then
        systemd-analyze verify "$UNIT_FILE" 2>&1 | grep -v "ollama.service" || true
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
}

main() {
    load_state
    parse_args "$@"
    require_root
    ((DRY_RUN)) && warn "dry-run：不会做任何改动"

    preflight
    ensure_user
    ensure_env_file
    setup_backend
    check_models
    build_frontend
    save_state
    install_service
    install_nginx
    save_state          # 防火墙放行结果在 install_nginx 之后才确定
    wait_healthy || true
    summary
}

main "$@"
