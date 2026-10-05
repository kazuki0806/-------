#!/bin/bash
# Macの「業務」フォルダを、秘密情報を除いて非公開のGitHubリポジトリに置く。
# クラウドのAIがMac側のcron・スクリプトを読むためのもの。1回目は初期化、2回目以降は差分をpushする。
#
#   bash mac_gyomu_push.sh            # 確認して push する
#   bash mac_gyomu_push.sh --dry-run  # 何が入るかを見るだけ（push しない）
#
# 入れないもの：.env・鍵・トークン・パスワード台帳（roster.json、cwログパス台帳）・codes.json・
#              node_modules・ログ・バックアップ・動画など。
# 入れるもの：スクリプト・設定・マニュアル・crontab の内容（crontab -l の結果を crontab_now.txt に書く）。
#            threads_actions の history.json・post_log.txt など、Macにしか無い状態ファイルも入れる（.git は入れない）。
set -u
SRC="${GYOMU_DIR:-$HOME/業務}"
DST="${GYOMU_EXPORT:-$HOME/業務_export}"
REPO="${GYOMU_REPO:-kazuki0806/mac-gyomu}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

[ -d "$SRC" ] || { echo "業務フォルダが見つかりません: $SRC"; exit 1; }
command -v git >/dev/null || { echo "git がありません"; exit 1; }

mkdir -p "$DST"
# 1. 秘密情報・大きいもの・他のリポジトリにあるものを除いてコピーする
rsync -a --delete --delete-excluded \
  --exclude '.git' --exclude 'node_modules' --exclude '__pycache__' --exclude '.venv' --exclude 'venv' \
  --exclude '.env' --exclude '*.env' --exclude '.dev.vars' --exclude '*.key' --exclude '*.pem' --exclude '*.p12' \
  --exclude '*secret*' --exclude '*Secret*' --exclude '*token*' --exclude '*Token*' --exclude '*.enc' \
  --exclude 'roster*.json' --exclude 'roster.*' --exclude 'backups' --exclude 'backup' --exclude '*_backup*' \
  --exclude 'codes.json' --exclude 'cwログパス台帳' --exclude 'cloudflare-values.txt' --exclude 'accounts_json*' \
  --exclude '*ACCOUNTS_JSON*' --exclude '*貼る用*' --exclude '*.bak.*' --exclude '*ログパス*' \
  --exclude 'credentials*.json' --exclude 'client_secret*.json' --exclude 'service_account*.json' \
  --exclude '*.log' --exclude '*.tgz' --exclude '*.zip' --exclude '*.tar' --exclude '*.tar.gz' \
  --exclude '*.mp4' --exclude '*.mov' --exclude '*.m4a' --exclude '*.wav' --exclude '*.sqlite' --exclude '*.db' \
  --exclude '.DS_Store' --exclude '*.bak' --exclude '*.bak_*' --exclude '*.broken.*' \
  "$SRC/" "$DST/"

# 2. いまの crontab を書き出す（Macでしか見られない情報の中で、いちばん大事なもの）
crontab -l > "$DST/crontab_now.txt" 2>/dev/null || echo "# crontab は空です" > "$DST/crontab_now.txt"
# ~/claude code/line-threads などの .env は入れない。あるファイル名だけ記録する
{ echo "# $(date '+%Y-%m-%d %H:%M') の時点で、業務フォルダの外にあるLINE関係のファイル（中身は入れない）";
  ls -la "$HOME/claude code/line-threads" 2>/dev/null; ls -la "$HOME/業務/line-sales" 2>/dev/null; } > "$DST/line_env_files.txt"

# 3. 秘密情報らしき文字列が残っているファイルは入れない（飛ばして続ける）
# 「値そのもの」だけを探す。キー名だけ（トークンを読むコードや .env の雛形）には反応しない。
HITS=$(grep -rIl -E 'LINE_CHANNEL_ACCESS_TOKEN=[A-Za-z0-9+/=_-]{40,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-ant-[A-Za-z0-9_-]{30,}|AIza[0-9A-Za-z_-]{30,}|secret_[A-Za-z0-9]{40,}|ntn_[A-Za-z0-9]{40,}|"(password|pass|パスワード)"\s*:\s*"[^"]{6,}"' "$DST" 2>/dev/null | grep -v '/.git/' | grep -vE '\.(example|template|md)$' | head -50)
if [ -n "$HITS" ]; then
  echo "★ 秘密情報らしき文字列があるファイルは入れずに飛ばします（一覧は skipped_secrets.txt に残す）:"
  echo "$HITS"
  echo "$HITS" | sed "s|^$DST/||" > "$DST/skipped_secrets.txt"
  echo "$HITS" | while IFS= read -r f; do [ -n "$f" ] && rm -f "$f"; done
fi

echo "== 入るファイルの数: $(find "$DST" -type f -not -path '*/.git/*' | wc -l | tr -d ' ')  サイズ: $(du -sh "$DST" | cut -f1)"
[ "$DRY" = "1" ] && { echo "(dry-run) ここで終わります。中身は $DST を見てください"; exit 0; }

# 4. git に入れて push する
cd "$DST"
[ -d .git ] || git init -q
cat > .gitignore <<'IGN'
.env
*.env
*.key
*.pem
*secret*
*token*
roster*.json
roster.*
backups/
*ACCOUNTS_JSON*
*貼る用*
*ログパス*
codes.json
cwログパス台帳/
node_modules/
__pycache__/
*.log
.DS_Store
IGN
git add -A
if git diff --cached --quiet; then echo "前回から変化なし"; exit 0; fi
git -c user.name="ikeda-mac" -c user.email="mac@local" commit -q -m "業務フォルダの同期 $(date '+%Y-%m-%d %H:%M')"
if ! git remote get-url origin >/dev/null 2>&1; then
  if command -v gh >/dev/null; then
    gh repo create "$REPO" --private --source=. --remote=origin --push || exit 1
  else
    echo "gh がありません。GitHubで非公開リポジトリ $REPO を作ってから、次を実行してください："
    echo "  cd \"$DST\" && git remote add origin https://github.com/$REPO.git && git branch -M main && git push -u origin main"
    exit 1
  fi
else
  git push -q -u origin HEAD || exit 1
fi
echo "== push しました: https://github.com/$REPO"
