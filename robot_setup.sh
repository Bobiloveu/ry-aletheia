#!/usr/bin/env bash
set -euo pipefail

# 小车首次部署唯一需要执行的脚本：仅配置最小运行权限，不在小车编译。
# 使用方式：sudo ./robot_setup.sh <运行控制台的普通账户>
if [[ $EUID -ne 0 ]]; then
  echo "请使用 sudo 执行：sudo ./robot_setup.sh <运行账户>" >&2
  exit 1
fi

RUN_USER="${1:-${SUDO_USER:-}}"
if [[ -z "$RUN_USER" ]] || ! id "$RUN_USER" >/dev/null 2>&1; then
  echo "请提供有效的运行账户，例如：sudo ./robot_setup.sh robot" >&2
  exit 1
fi

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SUPERVISORCTL="$(command -v supervisorctl || true)"
if [[ -z "$SUPERVISORCTL" ]]; then
  echo "未找到 supervisorctl，请确认 Supervisor 已安装。" >&2
  exit 1
fi
SUDOERS_FILE="/etc/sudoers.d/rover-qa-supervisor"
TEMP_FILE="$(mktemp)"
trap 'rm -f "$TEMP_FILE"' EXIT
printf '%s ALL=(root) NOPASSWD: %s status, %s start *, %s restart *\n' "$RUN_USER" "$SUPERVISORCTL" "$SUPERVISORCTL" "$SUPERVISORCTL" > "$TEMP_FILE"
visudo -cf "$TEMP_FILE"
install -o root -g root -m 0440 "$TEMP_FILE" "$SUDOERS_FILE"

TASK_DIR="/opt/ry/data/tasks/origin_tasks"
if [[ -d "$TASK_DIR" ]] && command -v setfacl >/dev/null 2>&1; then
  if ! setfacl -m "u:${RUN_USER}:rwx" "$TASK_DIR" || ! setfacl -d -m "u:${RUN_USER}:rwx" "$TASK_DIR"; then
    echo "提示：无法设置任务目录 ACL，请手工授予 $RUN_USER 写权限。" >&2
  fi
fi

echo "权限配置完成。请以普通账户 $RUN_USER 运行：$PROJECT_ROOT/dist/ry-aletheia"
