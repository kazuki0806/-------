#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timerex_gas.js に、10分ごとの見回り（threads-actions の tick.yml）へ合図を送る関数 ghDispatchTick_ を足す。

Mac で実行する:
  python3 gas_add_tick.py [timerex_gas.js のパス]   既定は ~/業務/timerex_gas.js

やること（池田さんの決まりどおり：バックアップ → 一時ファイル → 置き換え）
  1. ghDispatchDaily_ の直後に ghDispatchTick_ を追加する
  2. importTimeRexEmails と runChores_ の中で、ghDispatchDaily_ の次に ghDispatchTick_ を呼ぶ
すでに入っていれば何もしない。送るのは cw_pm/gas_push.py（このスクリプトは送らない）。
"""
import datetime
import os
import shutil
import sys
import tempfile

PATH = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/業務/timerex_gas.js")

FUNC = r'''
// ── 10分ごとの見回り（threads-actions の tick.yml）へ合図を送る ──────────────
// 予約投稿チェック・完了通知・20時のアラート・19/22時の通知・0時台の前日チェックは tick.yml の中で
// slot（日本時間 HH:mm）から出し分ける。ここは時刻を見て合図を送るだけ。
//   7時台・12時台・19〜23時台 … 10分ごと（取り込みの回ごと）
//   0・8・10・14・16・18時台 … 最初の10分に1回
// 同じ10分枠では1回だけ送る（印は GH_TICK_LAST）。結果は GH_TICK_RESULT に残る。
// 止めたいときは GH_DISPATCH_TOKEN のプロパティを消す（annken.yml と同じ）。
function ghDispatchTick_() {
  const p = PropertiesService.getScriptProperties();
  if (!p.getProperty("GH_DISPATCH_TOKEN")) return;
  const now = new Date();
  const hhmm = Utilities.formatDate(now, "Asia/Tokyo", "HH:mm");
  const h = Number(hhmm.slice(0, 2));
  const m = Number(hhmm.slice(3, 5));
  const every10 = (h === 7 || h === 12 || (h >= 19 && h <= 23));
  const once = ([0, 8, 10, 14, 16, 18].indexOf(h) >= 0) && m < 10;
  if (!every10 && !once) return;
  const slot = Utilities.formatDate(now, "Asia/Tokyo", "yyyy-MM-dd HH") + ":" + String(Math.floor(m / 10));
  if (p.getProperty("GH_TICK_LAST") === slot) return;
  // 先に印を付ける。途中で落ちても同じ枠で撃ち続けない
  p.setProperty("GH_TICK_LAST", slot);
  const out = ghDispatch_("tick.yml", { slot: hhmm });
  p.setProperty("GH_TICK_RESULT", hhmm + " " + out);
}
'''

CALL_OLD = '\n  try { ghDispatchDaily_(); } catch (e) { Logger.log("案件掲載の起動に失敗: " + e); }\n'
CALL_NEW = CALL_OLD + '  try { ghDispatchTick_(); } catch (e) { Logger.log("見回りの起動に失敗: " + e); }\n'
CALL_OLD2 = '\n    try { ghDispatchDaily_(); } catch (e) { Logger.log("案件掲載の起動に失敗: " + e); }\n'
CALL_NEW2 = CALL_OLD2 + '    try { ghDispatchTick_(); } catch (e) { Logger.log("見回りの起動に失敗: " + e); }\n'
ANCHOR = "function runChores_() {"


def main():
    if not os.path.exists(PATH):
        print("ファイルがありません: " + PATH)
        return 1
    src = open(PATH, encoding="utf-8").read()
    if "function ghDispatchTick_" in src:
        print("すでに ghDispatchTick_ が入っています。何もしません: " + PATH)
        return 0
    if "function ghDispatch_(" not in src or "function ghDispatchDaily_" not in src:
        print("ghDispatch_ / ghDispatchDaily_ が見つかりません。別セッションの変更が入った timerex_gas.js で実行してください")
        return 1
    if src.count(CALL_OLD) != 1 or src.count(CALL_OLD2) != 1 or src.count(ANCHOR) != 1:
        print("差し込む場所が想定と違います（importTimeRexEmails / runChores_ / ghDispatchDaily_ の呼び出し）。手で確認してください")
        return 1
    out = src.replace(CALL_OLD, CALL_NEW).replace(CALL_OLD2, CALL_NEW2).replace(ANCHOR, FUNC.lstrip("\n") + "\n" + ANCHOR)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = PATH + ".bak_" + stamp
    shutil.copy2(PATH, backup)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(PATH), prefix=".timerex_gas.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, PATH)
    print("足しました: " + PATH)
    print("バックアップ: " + backup)
    print("次は cw_pm で  python3 sync.py --check（差分なしを確認）→  python3 gas_push.py --check シート  →  python3 gas_push.py シート")
    return 0


if __name__ == "__main__":
    sys.exit(main())
