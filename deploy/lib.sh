#!/usr/bin/env bash
# install.sh / uninstall.sh 共用的函数与默认值。只被 source，不直接执行。

# ---------------------------------------------------------------- 默认配置 --
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="${STATE_FILE:-/etc/copernicus/deploy.conf}"   # install 记录部署参数，uninstall 据此还原

APP_DIR="${APP_DIR:-$REPO_DIR}"
SERVICE_USER="${SERVICE_USER:-copernicus}"
SERVICE_NAME="${SERVICE_NAME:-copernicus-backend}"
DATA_DIR="${DATA_DIR:-/data/copernicus}"
WEB_ROOT="${WEB_ROOT:-/var/www/copernicus}"
NGINX_CONF="${NGINX_CONF:-/etc/nginx/conf.d/copernicus.conf}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PORT="${PORT:-8000}"

# 由 install.sh / uninstall.sh 的参数解析设置
# shellcheck disable=SC2034
DRY_RUN=0
ASSUME_YES=0

# ------------------------------------------------------------------- 输出 --
log()  { printf '\033[32m[信息]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[警告]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m[错误]\033[0m %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

# ------------------------------------------------------------------- 执行 --
# 所有改动系统的命令都经过 run：--dry-run 时只打印、不执行
run() {
    if ((DRY_RUN)); then
        printf '  [dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

service_home() { getent passwd "$SERVICE_USER" | cut -d: -f6; }

# 以服务用户身份执行（dry-run 同样只打印）。runuser -u 不会重置 HOME，
# 不显式指定的话 pip/npm 会去写 root 的缓存目录并失败
run_as_service_user() {
    run runuser -u "$SERVICE_USER" -- env "HOME=$(service_home)" "$@"
}

have() { command -v "$1" >/dev/null 2>&1; }

require_root() {
    ((DRY_RUN)) && return 0
    [[ $EUID -eq 0 ]] || die "需要 root 权限，请使用 sudo 运行"
}

confirm() {
    ((ASSUME_YES)) && return 0
    local reply
    read -r -p "$1 [y/N] " reply
    [[ $reply == [yY] ]]
}

# --------------------------------------------------------------- 状态文件 --
save_state() {
    ((DRY_RUN)) && { echo "  [dry-run] 写入 $STATE_FILE"; return 0; }
    install -d -m 755 "$(dirname "$STATE_FILE")"
    {
        echo "# 由 deploy/install.sh 生成，deploy/uninstall.sh 读取"
        for key in APP_DIR SERVICE_USER SERVICE_NAME DATA_DIR WEB_ROOT NGINX_CONF PORT USER_CREATED FIREWALL_OPENED; do
            printf '%s=%q\n' "$key" "${!key:-}"
        done
    } >"$STATE_FILE"
}

# 先载入上次安装记录的参数作为默认值，再由命令行参数覆盖（调用顺序：load_state → 解析参数 → finalize_paths）
load_state() {
    # shellcheck disable=SC1090
    [[ -r $STATE_FILE ]] && source "$STATE_FILE"
    return 0
}

# shellcheck disable=SC2034  # UNIT_FILE 由 install.sh / uninstall.sh 使用
finalize_paths() {
    UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
}

# ------------------------------------------------------------------- 模板 --
# render_template <模板> <目标>：把 @VAR@ 替换为同名 shell 变量的值
render_template() {
    local src="$1" dest="$2" content
    content="$(<"$src")"
    local var
    for var in APP_DIR SERVICE_USER DATA_DIR WEB_ROOT PORT SERVER_NAME; do
        content="${content//@${var}@/${!var:-}}"
    done
    if [[ $content =~ @[A-Z_]+@ ]]; then
        die "模板 $src 中存在未替换的占位符：${BASH_REMATCH[0]}"
    fi
    if ((DRY_RUN)); then
        echo "  [dry-run] 渲染 $src -> $dest"
    else
        printf '%s\n' "$content" >"$dest"
    fi
}

# 校验并重载 nginx；校验失败返回 1，由调用方决定如何回滚
reload_nginx() {
    have nginx || return 0
    if ((DRY_RUN)); then echo "  [dry-run] nginx -t && systemctl reload nginx"; return 0; fi
    if nginx -t 2>/dev/null; then
        systemctl enable nginx >/dev/null 2>&1 || true
        systemctl reload nginx 2>/dev/null || systemctl start nginx
        return 0
    fi
    return 1
}
