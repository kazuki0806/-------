#!/usr/bin/env python3
"""週1回、Macの Claude Code の会話の履歴から、AIへの決まり（CLAUDE.md）とスキルの直し案を出す。

2026-10-05 作成。動画「AIエージェントが賢くなる7つの技」の1つ目（会話の履歴から決まりを直す）を、
池田さんの Mac で回すためのもの。直し案を出すだけで、決まりやスキルは書き換えない。
どれを反映するかは池田さんが決める。

流れ
  1. ~/.claude/projects/*/*.jsonl から、前回の実行以降に池田さんが打った発言だけを集める
     （AIの返事・道具の結果・自動で入る文は除く。直前のAIの返事は末尾だけ添える）
  2. パスワード・トークンらしき文字を伏せる
  3. 今の決まり（CLAUDE.md 全部）とスキル（SKILL.md）と一緒に Anthropic の API に渡す
  4. 直し案を 業務/weekly_review/proposals/YYYY-MM-DD.md に書き、公式LINEへ知らせる

置き場所
  直し案   ~/業務/weekly_review/proposals/   … 業務フォルダなので GitHub（mac-gyomu）へ同期される
  集めた発言 ~/.claude/weekly_review/        … 業務フォルダの外。GitHub には出ない
  状態     ~/.claude/weekly_review/state.json（前回うまくいった時刻）

動かし方
  python3 weekly_review.py --digest-only   発言を集めて件数を出すだけ（APIもLINEも使わない）
  python3 weekly_review.py --no-line       直し案まで作る。LINEには送らない
  python3 weekly_review.py --force         7日たっていなくても今すぐ作る
  python3 weekly_review.py                 7日たっていれば作ってLINEへ送る（refresh_5min.sh から呼ばれる）

Python 3.9（Mac標準の /usr/bin/python3）で動くように書いてある。
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
GYOMU = os.path.join(HOME, "業務")
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.join(HOME, ".claude", "projects")
PRIVATE = os.path.join(HOME, ".claude", "weekly_review")
STATE = os.path.join(PRIVATE, "state.json")
LOCK = os.path.join(PRIVATE, "run.lock")
PROPOSALS = os.path.join(HERE, "proposals")
LINE_ENV = os.path.join(HOME, "claude code", "line-threads", ".env")
LINE_TO = "U2b6c5b70e6a120fe46ae51142c48f134"   # 池田さん（notify_scheduled.py と同じ宛先）

sys.path.insert(0, os.path.join(GYOMU, "threads_actions"))

JST = dt.timezone(dt.timedelta(hours=9))
EVERY_DAYS = 7          # この日数たったら次を作る
FIRST_DAYS = 7          # 初回にさかのぼる日数
MAX_DAYS = 21           # 長く止まっていても、さかのぼるのはここまで
MODEL = os.environ.get("WEEKLY_REVIEW_MODEL", "claude-opus-5")   # auto_draft.py と同じ
MAX_TOKENS = 12000
MSG_LIMIT = 1200        # 発言1件の上限（長い貼り付けは頭と尻だけ残す）
PREV_LIMIT = 240        # 直前のAIの返事は末尾だけ
DIGEST_LIMIT = 120000   # 集めた発言全体の上限（文字）
RULE_FILE_LIMIT = 15000
RULES_LIMIT = 140000

# 指摘・直しらしい言い回し。上限を超えたとき、これを含む発言を優先して残す
FEEDBACK_WORDS = [
    "違う", "ちがう", "じゃなくて", "ではなく", "何度", "なんども", "前も", "前にも", "言った", "いった",
    "また", "やめて", "しないで", "するな", "直して", "なおして", "なんで", "なぜ", "おかしい",
    "見づらい", "みづらい", "わかりにくい", "分かりにくい", "長い", "短く", "毎回", "いつも",
    "勝手に", "確認して", "先に", "今後", "これから", "覚えて", "ルール", "決まり", "忘れ",
]

# 発言の頭がこれなら、人が打った文ではない（コマンドの記録・自動の通知など）
SKIP_PREFIX = ("<command-name>", "<command-message>", "<local-command", "<bash-", "<task-notification",
               "<system-reminder>", "Caveat:", "[Request interrupted", "<user-prompt-submit-hook>")

SECRET_PATTERNS = [
    (re.compile(r"LINE_CHANNEL_ACCESS_TOKEN=\S+"), "LINE_CHANNEL_ACCESS_TOKEN=[伏せ字]"),
    (re.compile(r"(ghp_|github_pat_|sk-ant-|sk-|ntn_|secret_|xox[abpr]-|AIza)[A-Za-z0-9_\-]{10,}"), "[伏せ字]"),
    (re.compile(r"(?i)(password|passwd|pass|pw|パスワード|パス|合言葉|暗証番号)(\s*[:：=は]\s*)\S+"), r"\1\2[伏せ字]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[メール]"),
    (re.compile(r"(?<![\w\-])0\d{1,4}-?\d{1,4}-?\d{3,4}(?![\w\-])"), "[電話]"),
]


def now():
    return dt.datetime.now(JST)


def log(msg):
    print("%s %s" % (now().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def parse_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(JST)
    except ValueError:
        return None


LONG_RUN = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{32,}(?![A-Za-z0-9_\-])")
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _long_run(m):
    # 32字以上の英数字の並びは鍵の可能性があるので伏せる。ゴールIDなどのUUIDは鍵ではないので残す
    return m.group(0) if UUID.fullmatch(m.group(0)) else "[伏せ字]"


def mask(text):
    for pat, rep in SECRET_PATTERNS:
        text = pat.sub(rep, text)
    return LONG_RUN.sub(_long_run, text)


def strip_tags(text):
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
    return text.strip()


def shorten(text, limit):
    if len(text) <= limit:
        return text
    head = int(limit * 0.7)
    tail = limit - head
    return "%s\n……（%d字を省略）……\n%s" % (text[:head], len(text) - limit, text[-tail:])


def text_of(content):
    """message.content から、人が書いた文の部分だけを取り出す。道具の結果だけの行は None。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text", ""))
    return "\n".join(parts) if parts else None


def project_name(cwd, dirname):
    # 発言の行にある作業場所（cwd）を使う。フォルダ名は日本語が - に潰れていて読めないため
    if cwd:
        return cwd.replace(HOME, "~")
    return dirname[-40:]


# ---------------------------------------------------------------- 1. 発言を集める

def collect(since):
    msgs = []
    files = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    sessions = set()
    seen = set()   # 同じ会話が作業場所ごとに別のフォルダへ記録されることがあるので、発言のIDで重複を除く
    for path in files:
        if dt.datetime.fromtimestamp(os.path.getmtime(path), JST) < since:
            continue
        dirname = os.path.basename(os.path.dirname(path))
        prev_ai = ""
        try:
            fh = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict) or d.get("isSidechain"):
                    continue
                kind = d.get("type")
                msg = d.get("message") or {}
                if kind == "assistant":
                    t = text_of(msg.get("content"))
                    if t and t.strip():
                        prev_ai = t.strip()
                    continue
                if kind != "user" or d.get("isMeta") or d.get("isCompactSummary"):
                    continue
                origin = d.get("origin")
                if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
                    continue
                ts = parse_ts(d.get("timestamp"))
                if ts is None or ts < since:
                    continue
                uid = d.get("uuid")
                if uid in seen:
                    continue
                t = text_of(msg.get("content"))
                if not t:
                    continue
                t = strip_tags(t)
                if not t or t.startswith(SKIP_PREFIX):
                    continue
                t = mask(shorten(t, MSG_LIMIT))
                msgs.append({
                    "ts": ts,
                    "project": project_name(d.get("cwd"), dirname),
                    "session": os.path.basename(path)[:8],
                    "text": t,
                    "prev": mask(prev_ai[-PREV_LIMIT:]) if prev_ai else "",
                    "feedback": any(w in t for w in FEEDBACK_WORDS),
                })
                if uid:
                    seen.add(uid)
                sessions.add(d.get("sessionId") or path)
    msgs.sort(key=lambda m: m["ts"])
    return msgs, len(sessions)


def render(m):
    head = "■ %s  %s  会話%s%s" % (m["ts"].strftime("%m/%d %H:%M"), m["project"], m["session"],
                                  "  ［指摘らしい］" if m["feedback"] else "")
    body = m["text"]
    if m["prev"]:
        body = "（直前のAIの返事の末尾）……%s\n（池田さん）%s" % (m["prev"].replace("\n", " "), body)
    return head + "\n" + body + "\n"


def build_digest(msgs):
    """上限に収まるよう、指摘らしい発言を優先し、残りは新しい順に入れる。最後は時刻順に並べ直す。"""
    blocks = [(m, render(m)) for m in msgs]
    chosen, total = [], 0
    for want in (True, False):
        for m, b in sorted(blocks, key=lambda x: x[0]["ts"], reverse=True):
            if m["feedback"] != want:
                continue
            if total + len(b) > DIGEST_LIMIT:
                continue
            chosen.append((m, b))
            total += len(b)
    chosen.sort(key=lambda x: x[0]["ts"])
    dropped = len(blocks) - len(chosen)
    return "\n".join(b for _, b in chosen), len(chosen), dropped


# ---------------------------------------------------------------- 2. 今の決まりとスキル

def rule_files():
    pats = [
        os.path.join(HOME, ".claude", "CLAUDE.md"),
        os.path.join(GYOMU, "CLAUDE.md"),
        os.path.join(GYOMU, "*", "CLAUDE.md"),
        os.path.join(GYOMU, ".claude", "rules", "*.md"),
        os.path.join(HOME, ".claude", "skills", "*", "SKILL.md"),
        os.path.join(GYOMU, ".claude", "skills", "*", "SKILL.md"),
        os.path.join(HOME, ".claude", "agents", "*.md"),
    ]
    seen, out = set(), []
    for p in pats:
        for f in sorted(glob.glob(p)):
            r = os.path.realpath(f)
            if r in seen or "/_archive/" in f or "/_claude_rules/" in f:
                continue
            seen.add(r)
            out.append(f)
    return out


def build_rules():
    parts, total = [], 0
    for f in rule_files():
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                body = fh.read()
        except OSError:
            continue
        shown = f.replace(HOME, "~")
        block = "=== ファイル: %s（%d字）===\n%s\n" % (shown, len(body), mask(shorten(body, RULE_FILE_LIMIT)))
        if total + len(block) > RULES_LIMIT:
            parts.append("=== ファイル: %s（上限のため中身は省略）===\n" % shown)
            continue
        parts.append(block)
        total += len(block)
    return "\n".join(parts)


# ---------------------------------------------------------------- 3. 直し案を作る

SYSTEM = """あなたは、池田さんと Claude Code の1週間の会話を読み、AIへの決まり（CLAUDE.md）とスキル（SKILL.md）の直し案を出す係です。
目的は、池田さんが同じ指摘を二度しなくて済むようにすることです。決まりやスキルを書き換えるのはあなたではなく、案を読んだ池田さんが選びます。

案にしてよいもの
- 池田さんが2回以上、別の場面で同じ趣旨の指摘・直し・やり直しを頼んでいるもの
- 1回でも「今後は」「これから」「毎回」「覚えて」など、決まりにしてほしいとはっきり言っているもの
- 1回でも、データを消した・誤送信した・二重に投稿したなど、大きな事故につながったもの

案にしないもの
- その場限りの好み、1回だけの細かい言い直し
- 今の決まりに既に書いてあり、守られているもの
- 決まりに書くと他の場面で困るもの

書き方の決まり（池田さんの決まりに合わせる）
- 1文目に結論。普通の文章で書く。表・太字・絵文字は使わない
- 会話から引用するときは40字以内の要約にする。顧客や社員の名前、パスワード、トークン、URLの鍵らしき部分は書かない
- 直す先は、今ある決まりの分け方に従う。振る舞い方は ~/.claude/CLAUDE.md、事業の前提は ~/業務/CLAUDE.md、そのフォルダだけの手順はそのフォルダの CLAUDE.md、決まった作業の手順はスキル
- 書く文は、そのまま貼れば済む完成した文にする
- 案は多くても8つ。少なくてよい。見つからなければ「今週は直し案なし」と書く

出力の形（Markdown。この見出しの名前を変えない）
# 今週の直し案
1〜2文の結論。

## 直し案1：（短い題）
対象ファイル：（フルパス）
直す場所：（節の名前。新しく足すなら「〇〇の節の末尾に追加」）
書く文：
> （そのまま貼る文。複数行可）
根拠：（いつ、何回、どんな指摘だったかの要約）
優先度：高／中／低

（直し案2以降も同じ形）

## 決まりにあるのに守られていないこと
決まりには書いてあるのに、AIが守らず池田さんが指摘したもの。どの決まりか、何回か、決まりの書き方をどう強めるか（または毎回の点検に入れるか）を書く。無ければ「なし」。

## スキルにできそうな繰り返し作業
池田さんが同じ手順を何度も頼んでいる作業。スキル名の案と、何をするスキルかを1〜2文で。無ければ「なし」。

## 提案
池田さんが次にすることを1〜3行で。反映したい案の番号を Claude Code に伝えれば反映される、と書く。
"""


def ask_claude(user_text):
    import secretstore   # ~/業務/threads_actions/secretstore.py（auto_draft.py と同じ鍵の置き場）
    sec = secretstore.read().get("services", {})
    key = sec.get("anthropic_api_key")
    if not key:
        raise RuntimeError("AnthropicのAPIキーが未登録です（set_anthropic_key.py）")
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    if sec.get("anthropic_workspace_id"):
        headers["anthropic-workspace-id"] = sec["anthropic_workspace_id"]
    payload = {"model": MODEL, "max_tokens": MAX_TOKENS, "system": SYSTEM,
               "messages": [{"role": "user", "content": user_text}]}
    data = json.dumps(payload).encode()
    last = None
    for attempt in range(3):
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=data,
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                d = json.load(r)
            text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
            if not text.strip():
                raise RuntimeError("返事が空でした（stop_reason=%s）" % d.get("stop_reason"))
            return text, d.get("usage", {})
        except urllib.error.HTTPError as e:
            last = "%s %s" % (e.code, e.read().decode("utf-8", "ignore")[:300])
            if e.code in (429, 500, 502, 503, 529):
                time.sleep(30 * (attempt + 1))
                continue
            raise RuntimeError(last)
        except (urllib.error.URLError, OSError) as e:
            last = str(e)
            time.sleep(20)
    raise RuntimeError(last or "Anthropicへの問い合わせに失敗しました")


# ---------------------------------------------------------------- 4. 書き出しと知らせ

def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def line_push(text):
    token = None
    with open(LINE_ENV, encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith("LINE_CHANNEL_ACCESS_TOKEN="):
                token = ln.split("=", 1)[1].strip().strip('"').strip("'")
    if not token:
        raise RuntimeError("line-threads/.env に LINE_CHANNEL_ACCESS_TOKEN がありません")
    body = json.dumps({"to": LINE_TO, "messages": [{"type": "text", "text": text[:4900]}]}).encode()
    req = urllib.request.Request("https://api.line.me/v2/bot/message/push", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError("LINE送信に失敗: %s" % r.status)


def line_text(path, proposal, period):
    titles = re.findall(r"^## (直し案\d+[：:].*)$", proposal, flags=re.M)
    lines = ["今週の直し案ができました（%s の会話から）。" % period]
    if titles:
        lines.append("案は%d件です。" % len(titles))
        lines += ["・" + t.strip() for t in titles]
    else:
        lines.append("今週は直し案がありませんでした。")
    lines.append("")
    lines.append("全文: " + path.replace(HOME, "~"))
    lines.append("反映したい案があれば、Claude Code に「今週の直し案の1と3を反映して」のように伝えてください。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 本体

def load_state():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def take_lock():
    os.makedirs(PRIVATE, exist_ok=True)
    try:
        os.mkdir(LOCK)
        return True
    except FileExistsError:
        if time.time() - os.path.getmtime(LOCK) > 3 * 3600:   # 3時間以上前のロックは前の回の残骸
            shutil.rmtree(LOCK, ignore_errors=True)
            os.mkdir(LOCK)
            return True
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest-only", action="store_true", help="発言を集めて件数を出すだけ")
    ap.add_argument("--no-line", action="store_true", help="LINEへ送らない")
    ap.add_argument("--force", action="store_true", help="7日たっていなくても作る")
    ap.add_argument("--days", type=int, help="さかのぼる日数を指定する")
    a = ap.parse_args()

    state = load_state()
    last_ok = parse_ts(state.get("last_ok"))
    t0 = now()
    if not (a.force or a.digest_only) and last_ok and t0 - last_ok < dt.timedelta(days=EVERY_DAYS):
        return   # まだ7日たっていない。refresh_5min.sh から6時間おきに呼ばれるので、黙って終わる

    if a.days:
        since = t0 - dt.timedelta(days=a.days)
    elif last_ok:
        since = max(last_ok, t0 - dt.timedelta(days=MAX_DAYS))
    else:
        since = t0 - dt.timedelta(days=FIRST_DAYS)
    period = "%s〜%s" % (since.strftime("%m/%d"), t0.strftime("%m/%d"))

    if not take_lock():
        log("前の回がまだ動いているので見送り")
        return
    try:
        msgs, sessions = collect(since)
        digest, kept, dropped = build_digest(msgs)
        fb = sum(1 for m in msgs if m["feedback"])
        log("期間 %s  会話%d本  発言%d件（指摘らしい%d件）  渡す%d件・上限で外した%d件  %d字"
            % (period, sessions, len(msgs), fb, kept, dropped, len(digest)))
        stamp = t0.strftime("%Y-%m-%d")
        write_atomic(os.path.join(PRIVATE, "digest-%s.md" % stamp), digest)
        if a.digest_only:
            log("集めた発言: %s" % os.path.join(PRIVATE, "digest-%s.md" % stamp))
            return
        if not msgs:
            log("期間内に発言が無いので、直し案は作らない")
            return

        rules = build_rules()
        user_text = ("期間：%s（会話%d本、池田さんの発言%d件。うち指摘らしいもの%d件）\n\n"
                     "【今の決まりとスキル】\n%s\n\n【この期間の池田さんの発言（時刻順）】\n%s"
                     % (period, sessions, len(msgs), fb, rules, digest))
        proposal, usage = ask_claude(user_text)
        head = ("<!-- %s 作成。期間 %s・会話%d本・発言%d件。model=%s in=%s out=%s。"
                "このファイルは案です。決まりは書き換えていません -->\n"
                % (t0.strftime("%Y-%m-%d %H:%M"), period, sessions, len(msgs), MODEL,
                   usage.get("input_tokens"), usage.get("output_tokens")))
        out = os.path.join(PROPOSALS, "%s.md" % stamp)
        write_atomic(out, head + mask(proposal))
        log("直し案: %s" % out)

        if not a.no_line:
            try:
                line_push(line_text(out, proposal, period))
                log("公式LINEへ知らせました")
            except Exception as e:   # 知らせに失敗しても案はできているので、成功扱いにする
                log("LINEへの知らせに失敗: %s" % e)

        state["last_ok"] = t0.isoformat()
        state["last_file"] = out
        write_atomic(STATE, json.dumps(state, ensure_ascii=False, indent=1))
    except Exception as e:
        log("失敗: %s（次の回にやり直す）" % e)
        raise
    finally:
        shutil.rmtree(LOCK, ignore_errors=True)


if __name__ == "__main__":
    main()
