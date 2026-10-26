"""ふもとっぱら キャンプ宿泊の空き監視 -> Gmail通知 (ブラウザ不要版)

環境変数:
  GMAIL_USER          送信元Gmailアドレス
  GMAIL_APP_PASSWORD  Googleアカウントの「アプリパスワード」(16桁)
  NOTIFY_TO           通知先(省略時はGMAIL_USER)
実行:
  pip install requests
  python fumo_watch.py            # 1回チェック
  python fumo_watch.py --dump     # 対象日の状態を表示するだけ(メール・記録なし)
  python fumo_watch.py --start 2027-01-10 --end 2027-01-12   # 期間指定(既定は12/30〜1/3)

動作状況の確認:
  status.html  最終チェック時刻・結果・日別の状態・直近の実行履歴(開くだけで見られる)
  run.log      実行ごとの1行ログ(OK / ERROR / NOTIFY)
"""
import os, sys, json, html, smtplib, datetime as dt
from email.message import EmailMessage
from pathlib import Path
import requests

# ===== ここはDevToolsの「calendars」リクエストに合わせて調整 =====
URL = "https://reserve.fumotoppara.net/api/user/reserve/calendars"
METHOD = "GET"                       # POST の場合は "POST"
PARAMS = {}                          # 例: {"siteGroupCd": "01", "stayDiv": "STAY"}
BODY = None                          # POST の場合 例: {"startDate": "2026-10-01", "endDate": "2027-01-31"}
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    # Request Headers に apiKey など独自ヘッダーがあればここへ追加
}
# ==================================================================

SITE_GROUP, STAY_DIV = "01", "STAY"          # キャンプ宿泊
JST = dt.timezone(dt.timedelta(hours=9))


def _arg(name, default):
    if name in sys.argv:
        return dt.date.fromisoformat(sys.argv[sys.argv.index(name) + 1])
    return default


START = _arg("--start", dt.date(2026, 12, 30))   # 監視期間(両端を含む)
END = _arg("--end", dt.date(2027, 1, 3))

STATE = Path("state.json")
LOG = Path("run.log")
PAGE = Path("status.html")
LABEL = {"1": "○", "2": "△", "3": "残りわずか", "8": "×", "9": "受付外"}


def is_open(row):
    # dispDiv: 8=×(満室) 9=受付外 / 1,2,3=予約可能
    return str(row["dispDiv"]) in ("1", "2", "3") and row["remainCount"] > 0


def fetch():
    r = requests.request(METHOD, URL, params=PARAMS, json=BODY, headers=HEADERS, timeout=30)
    r.raise_for_status()
    rows = r.json()["calendarsSiteDateList"]
    out = {}
    for row in rows:
        if row["siteGroupCd"] == SITE_GROUP and row["stayDiv"] == STAY_DIV:
            d = dt.date.fromisoformat(row["calDate"])
            if START <= d <= END:
                out[d.isoformat()] = row
    return out


def send_mail(rows):
    user, pw = os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"]
    msg = EmailMessage()
    msg["Subject"] = "【ふもとっぱら】キャンプ宿泊に空きが出ました"
    msg["From"], msg["To"] = user, os.environ.get("NOTIFY_TO", user)
    lines = [f"{d}  {LABEL.get(str(r['dispDiv']), r['dispDiv'])} (残り{r['remainCount']})"
             for d, r in sorted(rows.items())]
    msg.set_content("予約可能になった日:\n" + "\n".join(lines)
                    + "\n\nhttps://reserve.fumotoppara.net/reserved/reserved-date-selection")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(msg)


def log(level, text):
    stamp = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{stamp}\t{level}\t{text}\n")


def write_page(cur, error=None):
    """status.html を作る(最終チェック・日別状態・直近履歴)"""
    now = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    lines = LOG.read_text(encoding="utf-8").splitlines() if LOG.exists() else []
    recent = [l.split("\t") for l in lines[-30:]][::-1]
    last_ok = next((l[0] for l in recent if len(l) > 1 and l[1] in ("OK", "NOTIFY")), "-")
    last_notify = next((l[0] for l in recent if len(l) > 1 and l[1] == "NOTIFY"), "なし")

    rows_html = ""
    for d, r in sorted((cur or {}).items()):
        ok = is_open(r)
        cls, mark = ("open", "空き") if ok else ("full", "×")
        label = LABEL.get(str(r["dispDiv"]), r["dispDiv"])
        rows_html += (f'<tr class="{cls}"><td>{d}</td><td>{html.escape(str(label))}</td>'
                      f'<td>{r["remainCount"]}</td><td>{mark}</td></tr>')
    log_html = "".join(
        f'<tr class="{html.escape(l[1])}"><td>{html.escape(l[0])}</td><td>{html.escape(l[1])}</td>'
        f'<td>{html.escape(l[2] if len(l) > 2 else "")}</td></tr>' for l in recent if len(l) > 1)
    banner = (f'<p class="err">⚠ 直近のチェックに失敗: {html.escape(error)}</p>' if error
              else '<p class="good">✔ 正常に動作中</p>')

    PAGE.write_text(f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60"><title>ふもとっぱら監視</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:720px;margin:16px auto;padding:0 16px;color:#222}}
table{{border-collapse:collapse;width:100%;margin:8px 0 24px}}
td,th{{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;font-size:14px}}
tr.open td{{background:#e6f7e9;font-weight:bold}} tr.ERROR td{{color:#b00020}} tr.NOTIFY td{{background:#fff6d6}}
.good{{color:#0a7a2f}} .err{{color:#b00020;font-weight:bold}} .meta{{color:#555;font-size:14px}}
</style></head><body>
<h1>ふもとっぱら 空き監視</h1>{banner}
<p class="meta">対象: キャンプ宿泊 {START} 〜 {END}<br>
最終チェック: {now}<br>最後に成功: {html.escape(last_ok)}<br>最後の通知: {html.escape(last_notify)}</p>
<h2>日別の状態</h2>
<table><tr><th>日付</th><th>表示</th><th>残り</th><th>判定</th></tr>{rows_html}</table>
<h2>直近の実行履歴</h2>
<table><tr><th>時刻</th><th>種別</th><th>内容</th></tr>{log_html}</table>
</body></html>""", encoding="utf-8")


def main():
    dump = "--dump" in sys.argv
    try:
        cur = fetch()
        if not cur:
            raise RuntimeError("対象日のデータが取れませんでした(URL/パラメータを確認)")
    except Exception as e:
        if dump:
            raise
        log("ERROR", f"{type(e).__name__}: {e}")
        write_page(None, error=f"{type(e).__name__}: {e}")
        print("ERROR:", e)
        sys.exit(1)

    now_open = {d: is_open(r) for d, r in cur.items()}
    summary = " ".join(f"{d[5:]}={'空' if o else '×'}" for d, o in sorted(now_open.items()))
    print(summary)
    if dump:
        return

    prev = json.loads(STATE.read_text()) if STATE.exists() else None
    if prev is None:                                  # 初回は基準を記録するだけ
        log("OK", f"初回(基準を記録) {summary}")
    else:
        # 前回は×だった日が空きに変わったときだけ通知(新しく期間に入った日は基準記録のみ)
        newly = {d: cur[d] for d, o in now_open.items() if o and prev.get(d) is False}
        if newly:
            try:
                send_mail(newly)
                log("NOTIFY", "通知送信: " + ",".join(sorted(newly)))
            except Exception as e:
                log("ERROR", f"メール送信失敗: {type(e).__name__}: {e}")
                write_page(cur, error=f"メール送信失敗: {e}")
                sys.exit(1)            # 状態を更新しない=次回また通知を試みる
        else:
            log("OK", summary)
    STATE.write_text(json.dumps(now_open))
    write_page(cur)


if __name__ == "__main__":
    main()
