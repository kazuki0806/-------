# 週1回の直し案づくり（weekly_review.py）

池田さんの Mac の Claude Code の会話の履歴から、池田さんが何度も言った指摘を拾い、AIへの決まり（CLAUDE.md）とスキル（SKILL.md）の直し案を出す。決まりやスキルは書き換えない。どれを反映するかは池田さんが決める。

会話の履歴（池田さんの発言）を Anthropic の API に送る。2026-10-05 に池田さんがこれを許可した。

置き場所（Mac）
- スクリプト: ~/業務/weekly_review/weekly_review.py
- 直し案: ~/業務/weekly_review/proposals/YYYY-MM-DD.md（業務フォルダなので GitHub の mac-gyomu にも上がる。中身は要約だけ）
- 集めた発言: ~/.claude/weekly_review/digest-YYYY-MM-DD.md（業務フォルダの外。GitHub には出ない）
- 前回うまくいった時刻: ~/.claude/weekly_review/state.json

外に出しすぎないための工夫
- 集めるのは池田さんが打った発言だけ。AIの返事は直前の末尾240字だけ添える。道具の結果や自動で入る文は入れない
- パスワード・トークン・32字以上の英数字の並び・メールアドレス・電話番号は伏せ字にしてから API に渡す（ゴールIDのようなUUIDは残す）
- 直し案の中の引用は40字以内の要約にし、名前や鍵は書かないよう AI に指示している

使う鍵
- Anthropic の API キーは auto_draft.py と同じ secretstore（~/業務/threads_actions/secretstore.py）から読む
- 公式LINEのトークンは notify_scheduled.py と同じ ~/claude code/line-threads/.env から読む

動かし方
- 発言を集めて件数を見るだけ（API も LINE も使わない）: python3 weekly_review.py --digest-only
- 直し案まで作る。LINE には送らない: python3 weekly_review.py --force --no-line
- 7日たっていれば作って LINE へ送る: python3 weekly_review.py

週1回動かす方法：refresh_5min.sh の1日1回の手順の並び（step rules の次）に、6時間おきに呼ぶ1行を足す案。7日たっているかはスクリプト側で判断するので、Mac が寝ていた週も起きた最初の回で動く。足すのは、Mac の Claude Code で中身を確かめてから。
