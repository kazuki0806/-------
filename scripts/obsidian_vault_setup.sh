#!/bin/bash
# Obsidian保管庫「Obsidian Vault」を非公開 GitHub リポジトリ kazuki0806/obsidian-vault に同期する初期設定。
# Mac 上で実行する。段階ごとに止まって結果を出す。
#
#   bash obsidian_vault_setup.sh find      # 1. 保管庫を探す
#   bash obsidian_vault_setup.sh check     # 2. 秘密・個人情報の疑いがあるファイル名を一覧（中身は出さない）
#   bash obsidian_vault_setup.sh ignore [除外ファイル...]   # 2. .gitignore を作る（引数は追加で除外する相対パス）
#   bash obsidian_vault_setup.sh push      # 3. git init → gh repo create --private → 最初のコミット → push → 非公開を確認
#   bash obsidian_vault_setup.sh cron      # 4. 30分おきの同期を cron に入れて、一度手で動かす
#
# 保管庫が複数見つかった場合や、場所を固定したい場合は OBSIDIAN_VAULT=/path/to/vault を先に付ける。
set -u
REPO="kazuki0806/obsidian-vault"
SYNC_SCRIPT="$(cd "$(dirname "$0")" && pwd)/obsidian_vault_sync.sh"
MARKER="池田業務/Threads/Threads知識ベース.md"

find_vault() {
  local roots=("$HOME/Documents" "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents" "$HOME")
  local cands=()
  for r in "${roots[@]}"; do
    [ -d "$r" ] || continue
    while IFS= read -r d; do
      [ -d "$d/.obsidian" ] && cands+=("$d")
    done < <(find "$r" -maxdepth 3 -type d -name "Obsidian Vault" 2>/dev/null)
  done
  # 重複を除く
  printf '%s\n' "${cands[@]}" | awk '!seen[$0]++'
}

resolve_vault() {
  if [ -n "${OBSIDIAN_VAULT:-}" ]; then VAULT="$OBSIDIAN_VAULT"; return; fi
  local list; list="$(find_vault)"
  local n; n="$(printf '%s\n' "$list" | grep -c . || true)"
  if [ "$n" -eq 0 ]; then echo "保管庫「Obsidian Vault」（.obsidian あり）が見つかりません。OBSIDIAN_VAULT=/path で指定してください。" >&2; exit 1; fi
  if [ "$n" -gt 1 ]; then
    echo "候補が複数あります。OBSIDIAN_VAULT=... を付けてどれか選んでください:" >&2
    printf '  %s\n' $list >&2; exit 1
  fi
  VAULT="$list"
}

cmd_find() {
  echo "== 1. 保管庫の場所"
  local list; list="$(find_vault)"
  if [ -z "$list" ]; then echo "見つかりません"; exit 1; fi
  while IFS= read -r v; do
    if [ -f "$v/$MARKER" ]; then echo "  $v   （$MARKER あり）"; else echo "  $v   （$MARKER なし）"; fi
  done <<< "$list"
  [ "$(printf '%s\n' "$list" | grep -c .)" -gt 1 ] && echo "複数あります。使う物を OBSIDIAN_VAULT=... で指定してください。" || true
}

cmd_check() {
  resolve_vault
  echo "== 2. 秘密・個人情報の疑いがあるファイル（中身は表示しません）: $VAULT"
  cd "$VAULT" || exit 1
  local pat
  pat='(password|passwd|パスワード|api[_ -]?key|secret|token|トークン|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-|BEGIN (RSA|OPENSSH) PRIVATE KEY|[0-9]{2,4}-[0-9]{2,4}-[0-9]{3,4}|〒?[0-9]{3}-[0-9]{4}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|住所|電話番号)'
  grep -rIlE --exclude-dir=.obsidian --exclude-dir=.git --exclude-dir=.trash "$pat" . 2>/dev/null | sed 's#^\./##' | sort
  echo "-- 上の一覧を見て、入れないファイルがあれば: bash $0 ignore '相対パス1' '相対パス2'"
}

cmd_ignore() {
  resolve_vault
  cd "$VAULT" || exit 1
  {
    echo ".obsidian/workspace.json"
    echo ".obsidian/workspace-mobile.json"
    echo ".obsidian/cache"
    echo ".trash/"
    echo ".DS_Store"
    for f in "$@"; do echo "$f"; done
  } > .gitignore
  echo "== 2. .gitignore を作成: $VAULT/.gitignore"; cat .gitignore
}

cmd_push() {
  resolve_vault
  cd "$VAULT" || exit 1
  echo "== 3. 非公開リポジトリ $REPO"
  if [ -d .git ]; then
    echo "既に git リポジトリです。今の状態（ここで止まります）:"
    git remote -v; git status --short | head -30; git log --oneline -5 2>/dev/null; exit 2
  fi
  command -v gh >/dev/null || { echo "gh がありません（brew install gh）。止まります。"; exit 1; }
  gh auth status >/dev/null 2>&1 || { echo "gh がログインしていません（gh auth login）。止まります。"; exit 1; }
  [ -f .gitignore ] || { echo ".gitignore がありません。先に: bash $0 ignore"; exit 1; }
  git init -q -b main
  gh repo create "$REPO" --private --source=. --remote=origin || exit 1
  git add -A
  git commit -q -m "Obsidian保管庫の同期を開始"
  git push -u origin main || exit 1
  echo "-- 公開範囲:"; gh repo view "$REPO" --json visibility,url -q '.visibility + "  " + .url'
}

cmd_cron() {
  resolve_vault
  echo "== 4. 30分おきの自動同期"
  chmod +x "$SYNC_SCRIPT"
  local line="*/30 * * * * OBSIDIAN_VAULT='$VAULT' '$SYNC_SCRIPT' >> '$HOME/Library/Logs/obsidian-vault-sync.log' 2>&1"
  local cronfile=""
  for c in "$VAULT/業務/cron/crontab.txt" "$HOME/業務/cron/crontab.txt"; do [ -f "$c" ] && { cronfile="$c"; break; }; done
  if [ -n "$cronfile" ]; then
    grep -qF "$SYNC_SCRIPT" "$cronfile" || printf '%s\n' "$line" >> "$cronfile"
    crontab "$cronfile" && echo "crontab に反映: $cronfile"
  else
    ( crontab -l 2>/dev/null | grep -vF "$SYNC_SCRIPT"; echo "$line" ) | crontab -
    echo "業務/cron/crontab.txt が無いので crontab に直接追加しました"
  fi
  echo "-- 追加した行:"; echo "$line"
  echo "-- 一度手で実行:"
  OBSIDIAN_VAULT="$VAULT" "$SYNC_SCRIPT"; echo "終了コード $?"
  tail -3 "$HOME/Library/Logs/obsidian-vault-sync.log" 2>/dev/null
  echo "-- GitHub 側の最新コミット:"; gh api "repos/$REPO/commits?per_page=1" -q '.[0].commit.message + "  " + .[0].commit.committer.date'
}

case "${1:-}" in
  find) cmd_find ;; check) cmd_check ;; ignore) shift; cmd_ignore "$@" ;; push) cmd_push ;; cron) cmd_cron ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
