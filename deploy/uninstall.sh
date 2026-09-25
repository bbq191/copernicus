#!/usr/bin/env bash
# Copernicus 卸载：撤销 install.sh 安装的系统级配置。
#
# 默认只移除服务、Nginx 配置与前端发布目录；数据与代码需显式指定才会删除。
# 永远不会触碰：代码仓库本身、backend/.env、模型文件、Ollama、NVIDIA 驱动。

set -Eeuo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PURGE_DATA=0
PURGE_ENV=0
REMOVE_USER=0
USER_CREATED="${USER_CREATED:-0}"
FIREWALL_OPENED="${FIREWALL_OPENED:-0}"

usage() {
    cat <<USAGE
用法：sudo deploy/uninstall.sh [选项]

  --purge-data    删除数据目录（上传的音视频与全部任务结果，不可恢复）
  --purge-env     删除 Python 虚拟环境与前端 node_modules（可重新安装）
  --remove-user   删除服务用户（仅当该用户由 install.sh 创建时生效）
  --dry-run       只打印将执行的操作
  -y, --yes       不询问确认
  -h, --help      显示本帮助

部署参数（用户、目录、服务名）读取自 $STATE_FILE，
也可用环境变量 SERVICE_NAME / DATA_DIR / WEB_ROOT / APP_DIR 覆盖。
USAGE
}

parse_args() {
    while (($#)); do
        case "$1" in
            --purge-data)  PURGE_DATA=1; shift ;;
            --purge-env)   PURGE_ENV=1; shift ;;
            --remove-user) REMOVE_USER=1; shift ;;
            --dry-run)     DRY_RUN=1; shift ;;
            -y|--yes)      ASSUME_YES=1; shift ;;
            -h|--help)     usage; exit 0 ;;
            *) usage >&2; die "未知选项：$1" ;;
        esac
    done
    finalize_paths
}

# 删除前展示目标，确认后才动手；目录不存在则静默跳过
remove_dir() {
    local dir="$1" why="$2"
    [[ -d $dir ]] || return 0
    # 防呆：拒绝删除根目录、家目录等明显危险的路径
    case "$(realpath "$dir")" in
        /|/home|/root|/opt|/var|/usr|/etc|/data) die "拒绝删除危险路径：$dir" ;;
    esac
    confirm "删除 $dir（$why）？" || { log "已保留 $dir"; return 0; }
    run rm -rf -- "$dir"
}

stop_service() {
    step "停止并移除 systemd 服务"
    if [[ -f $UNIT_FILE ]]; then
        run systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
        run rm -f "$UNIT_FILE"
        run systemctl daemon-reload
        run systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true
    else
        log "未发现 $UNIT_FILE，跳过"
    fi
}

remove_nginx() {
    step "移除 Nginx 配置"
    if [[ -f $NGINX_CONF ]]; then
        run rm -f "$NGINX_CONF"
        reload_nginx || warn "nginx 配置校验失败，请手工检查 nginx -t（本脚本只删除了 $NGINX_CONF）"
    else
        log "未发现 $NGINX_CONF，跳过"
    fi
    if ((FIREWALL_OPENED)) && have firewall-cmd; then
        run firewall-cmd --permanent --remove-service=http
        run firewall-cmd --reload
    fi
}

remove_files() {
    step "清理文件"
    remove_dir "$WEB_ROOT" "前端发布目录"
    ((PURGE_ENV)) && {
        remove_dir "$APP_DIR/backend/.venv" "Python 虚拟环境"
        remove_dir "$APP_DIR/frontend/node_modules" "前端依赖"
        remove_dir "$APP_DIR/frontend/dist" "前端构建产物"
    }
    if ((PURGE_DATA)); then
        remove_dir "$DATA_DIR" "上传文件与任务结果，不可恢复"
    else
        log "保留数据目录 $DATA_DIR（加 --purge-data 删除）"
    fi
}

remove_user() {
    ((REMOVE_USER)) || return 0
    if [[ $USER_CREATED != 1 ]]; then
        warn "用户 $SERVICE_USER 不是由 install.sh 创建的，不删除"
    elif id "$SERVICE_USER" >/dev/null 2>&1 && confirm "删除用户 $SERVICE_USER 及其 home？"; then
        run userdel --remove "$SERVICE_USER"
    fi
}

main() {
    load_state
    parse_args "$@"
    require_root
    ((DRY_RUN)) && warn "dry-run：不会做任何改动"
    [[ -r $STATE_FILE ]] || warn "未找到 $STATE_FILE，使用默认参数（服务 $SERVICE_NAME、数据 $DATA_DIR）"

    stop_service
    remove_nginx
    remove_files
    remove_user
    ((DRY_RUN)) || rm -f "$STATE_FILE"
    log "卸载完成。代码目录 $APP_DIR、.env 与模型文件未改动。"
}

main "$@"
