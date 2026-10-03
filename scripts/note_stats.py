#!/usr/bin/env python3
"""noteにログインして、記事ごとの閲覧数・スキ・コメントの累計を取る。

ログイン情報は環境変数から読む（チャットやリポジトリには書かない）:
  NOTE_SESSION                 ブラウザの Cookie「_note_session_v5」の値（優先して使う）。
                               切れたら取り直す
  NOTE_EMAIL / NOTE_PASSWORD   メール・パスワードでのログイン（2026-10-03 時点で reCAPTCHA に止められる）

出力（--out PATH、JSON）:
  {"fetched_at", "last_calculate_at", "date", "totals": {"pv","like","comment"},
   "notes": [{"key","name","read","like","comment"}]}
  date は noteが集計した日（last_calculate_at の日付、日本時間）。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

import requests

BASE = "https://note.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
JST = dt.timezone(dt.timedelta(hours=9))


def login(s):
    """Cookie があれば先に使う。メール・パスワードは reCAPTCHA で止められることが多いので、Cookie が無い時だけ試す。"""
    cookie = os.environ.get("NOTE_SESSION")
    if cookie:
        s.cookies.set("_note_session_v5", cookie.strip(), domain=".note.com")
        return "cookie"
    email, password = os.environ.get("NOTE_EMAIL"), os.environ.get("NOTE_PASSWORD")
    if email and password:
        r = s.post(f"{BASE}/api/v1/sessions/sign_in",
                   json={"login": email, "password": password}, timeout=30)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.ok and "error" not in body:
            return "password"
        code = (body.get("error") or {}).get("code", "")
        raise SystemExit(f"メール・パスワードでのログインに失敗（HTTP {r.status_code} {code}）。"
                         "reCAPTCHA で止められる時は NOTE_SESSION（Cookie _note_session_v5 の値）を環境変数に入れる")
    raise SystemExit("ログインできない：NOTE_SESSION（または NOTE_EMAIL・NOTE_PASSWORD）を環境変数に入れる")


def fetch_stats(s):
    notes, page, head = [], 1, None
    while True:
        r = s.get(f"{BASE}/api/v1/stats/pv", params={"filter": "all", "page": page, "sort": "pv"}, timeout=30)
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise SystemExit(f"統計を取れない（ログインが切れている可能性。NOTE_SESSION を取り直す）: {body['error']}")
        d = body.get("data") or {}
        head = head or d
        for n in d.get("note_stats") or []:
            notes.append({
                "key": n.get("key"),
                "name": n.get("name"),
                "read": n.get("read_count") or 0,
                "like": n.get("like_count") or 0,
                "comment": n.get("comment_count") or 0,
            })
        if d.get("last_page") in (True, None) or page >= 50:
            break
        page += 1
    return head or {}, notes


def calc_date(text, fallback):
    m = re.match(r"^\s*(\d{4})/(\d{1,2})/(\d{1,2})", text or "")
    return dt.date(int(m[1]), int(m[2]), int(m[3])) if m else fallback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json", "Referer": f"{BASE}/sitesettings/stats"})
    how = login(s)
    head, notes = fetch_stats(s)
    now = dt.datetime.now(JST)
    totals = {
        "pv": head.get("total_pv", sum(n["read"] for n in notes)),
        "like": head.get("total_like", sum(n["like"] for n in notes)),
        "comment": head.get("total_comment", sum(n["comment"] for n in notes)),
    }
    out = {
        "fetched_at": now.isoformat(timespec="minutes"),
        "login": how,
        "last_calculate_at": head.get("last_calculate_at"),
        "date": calc_date(head.get("last_calculate_at"), now.date()).isoformat(),
        "totals": totals,
        "notes": notes,
    }
    with open(a.out, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"note: {out['date']} 閲覧累計 {totals['pv']}・スキ {totals['like']}（{len(notes)}記事、集計 {out['last_calculate_at']}）")


if __name__ == "__main__":
    sys.exit(main())
