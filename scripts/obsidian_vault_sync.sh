#!/bin/bash
# Obsidian保管庫を GitHub に同期する（cron から30分おきに呼ぶ）。
# 変更が無ければ何もしない。失敗はログに残す。
# 使い方: obsidian_vault_sync.sh [保管庫のパス]   （省略時は $OBSIDIAN_VAULT）
set -u
VAULT="${1:-${OBSIDIAN_VAULT:-}}"
LOG="${OBSIDIAN_SYNC_LOG:-$HOME/Library/Logs/obsidian-vault-sync.log}"
mkdir -p "$(dirname "$LOG")"
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

# cron は PATH が短いので git / gh の場所を足す
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

if [ -z "$VAULT" ] || [ ! -d "$VAULT/.git" ]; then
  log "ERROR 保管庫が見つからない、または git リポジトリではない: '$VAULT'"
  exit 1
fi
cd "$VAULT" || { log "ERROR cd 失敗: $VAULT"; exit 1; }

# iCloud 等で同期中のファイルを避けるため、先にリモートを取り込む（失敗しても続行）
git pull --rebase --autostash --quiet origin main 2>>"$LOG" || log "WARN pull に失敗（続行）"

git add -A
if git diff --cached --quiet; then
  exit 0   # 変更なし。何もしない
fi

MSG="同期 $(date '+%Y-%m-%d %H:%M')"
if ! git commit -q -m "$MSG"; then
  log "ERROR commit 失敗"; exit 1
fi
if git push -q origin main 2>>"$LOG"; then
  log "OK push: $MSG ($(git rev-parse --short HEAD))"
else
  log "ERROR push 失敗: $MSG"; exit 1
fi
