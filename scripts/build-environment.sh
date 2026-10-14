#!/usr/bin/env bash
# Sourced by release entries. Reuse an installed environment; never install or
# update dependencies or the lock file as a side effect of starting a build.
aletheia_enter_build_environment() {
  local build_project_root="$1" build_entry_script="$2"
  shift 2
  cd "$build_project_root"
  if [[ "${PIXI_PROJECT_ROOT:-}" == "$build_project_root" ]]; then
    return
  fi
  if command -v pixi >/dev/null 2>&1 && [[ -x "$build_project_root/.pixi/envs/default/bin/python3" ]]; then
    echo "正在使用工程已安装的 Pixi 构建环境..."
    exec pixi run --frozen --no-install --manifest-path "$build_project_root/pixi.toml" bash "$build_entry_script" "$@"
  fi
}
