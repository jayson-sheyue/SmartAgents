# shellcheck shell=bash
# 统一环境加载：.env（密钥总表）→ env/local.env（本地覆盖）
# 用法：source "$ROOT/scripts/lib/load_env.sh" && load_smartagents_env "$ROOT"

load_smartagents_env() {
  local root="${1:?}"

  if [ ! -f "$root/.env" ]; then
    echo "❌ 缺少根 .env，请：cp .env.example .env 并填写" >&2
    return 1
  fi
  if [ ! -f "$root/env/local.env" ]; then
    echo "❌ 缺少 env/local.env，请：cp env/local.env.example env/local.env" >&2
    return 1
  fi

  set -a && source "$root/.env" && set +a
  echo "📄 base: $root/.env"
  set -a && source "$root/env/local.env" && set +a
  echo "📄 local: $root/env/local.env"
  return 0
}
