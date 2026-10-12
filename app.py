"""Lead dashboard + API (Flask, WSGI-ready for cPanel Passenger).

Leads live in MariaDB (see db.py). Local run:  python app.py
cPanel: passenger_wsgi.py imports `app` from this file.
"""
import hmac, io, os, threading, webbrowser
from datetime import datetime

from flask import Flask, Response, jsonify, request, send_file

import config
import db

try:                      # needs selenium/bs4/lxml; optional on the server
    import scraper
except ImportError:
    scraper = None

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
JOB = {"state": "idle", "log": [], "total": 0, "done": 0, "current": "", "reviews": 0, "failed": 0}
STOP = threading.Event()
LOCK = threading.Lock()
TABLE_COLS = ["company", "review_title", "rating", "review_date", "reviewer_name",
              "reviewer_position", "industry", "location"]
BUCKETS = ["5.0", "4.5", "4.0", "3.5", "3.0", "Below 3"]


def scraper_enabled():
    return bool(config.ENABLE_SCRAPER and scraper is not None and scraper.chrome_path())


def log(msg):
    JOB["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    del JOB["log"][:-500]


# ---------------------------------------------------------------- auth
def _same(a, b):
    return hmac.compare_digest(a.encode(), b.encode())


@app.before_request
def guard():
    if request.path == "/health":
        return None
    if request.path == "/api/ingest":
        if not config.INGEST_API_KEY:
            return jsonify(error="INGEST_API_KEY is not configured on the server."), 503
        if not _same(request.headers.get("x-api-key", ""), config.INGEST_API_KEY):
            return jsonify(error="Invalid API key."), 401
        return None
    if not config.APP_PASSWORD:
        return Response("APP_PASSWORD is not configured on the server.", 503)
    a = request.authorization
    if not (a and _same(a.username or "", config.APP_USER) and _same(a.password or "", config.APP_PASSWORD)):
        return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Lead dashboard"'})
    return None


@app.errorhandler(Exception)
def on_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    app.logger.exception("Unhandled error")
    return jsonify(error=str(e)), 500


# ---------------------------------------------------------------- scraping (optional)
def worker(p):
    try:
        JOB["state"] = "starting"
        scraper.run_scrape(p["category"], p["max_companies"], p["max_dir_pages"],
                           (2, 4), log=log, state=JOB, stop=STOP, resume=p["resume"],
                           save=db.upsert_leads)
        JOB["state"] = "stopped" if STOP.is_set() else "finished"
        log("Stopped by user." if STOP.is_set() else "Finished.")
    except BaseException as e:   # includes SystemExit from the scraper
        JOB["state"] = "error"; log(f"ERROR: {e}")


def rating_range():
    try:
        return float(request.args.get("min", 0)), float(request.args.get("max", 5))
    except ValueError:
        return 0.0, 5.0


def bucket(r):
    if r >= 5: return "5.0"
    if r < 3: return "Below 3"
    return f"{int(r * 2) / 2:.1f}"


@app.get("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.post("/api/start")
def api_start():
    if not scraper_enabled():
        return jsonify(error="Scraping is disabled on this server. Use run_weekly.py on a machine with Chrome."), 400
    d = request.get_json(force=True)
    cat = (d.get("category") or "").strip()
    if not cat.startswith("https://clutch.co/"):
        return jsonify(error="Category URL must start with https://clutch.co/"), 400
    with LOCK:
        if JOB["state"] in ("starting", "running"):
            return jsonify(error="A scrape is already running."), 409
        STOP.clear()
        JOB.update(state="starting", log=[], total=0, done=0, current="", reviews=0, failed=0)
    p = {"category": cat,
         "max_companies": max(1, min(int(d.get("max_companies", 5)), 500)),
         "max_dir_pages": max(1, min(int(d.get("max_dir_pages", 1)), 20)),
         "resume": not bool(d.get("refresh", False))}
    threading.Thread(target=worker, args=(p,), daemon=True).start()
    return jsonify(ok=True)


@app.post("/api/stop")
def api_stop():
    STOP.set()
    return jsonify(ok=True)


@app.get("/api/status")
def api_status():
    return jsonify({k: JOB[k] for k in ("state", "total", "done", "current", "reviews", "failed")}
                   | {"log": JOB["log"][-300:], "scraper_enabled": scraper_enabled()})


# ---------------------------------------------------------------- leads
@app.post("/api/ingest")
def api_ingest():
    """Receives leads pushed by run_weekly.py: {"rows": [ {...review...}, ... ]}"""
    d = request.get_json(force=True, silent=True) or {}
    rows = d.get("rows")
    if not isinstance(rows, list):
        return jsonify(error='Body must be JSON like {"rows": [...]}'), 400
    n = db.upsert_leads([r for r in rows if isinstance(r, dict)])
    return jsonify(ok=True, stored=n)


@app.get("/api/results")
def api_results():
    lo, hi = rating_range()
    st = db.stats(lo, hi)
    counts = {}
    for rating, n in st["dist"]:
        counts[bucket(rating)] = counts.get(bucket(rating), 0) + n
    rows = [{k: ("" if r[k] is None else r[k]) for k in TABLE_COLS} for r in db.fetch(lo, hi, 200)]
    return jsonify(total=st["total"], companies=st["companies"], matching=st["matching"], avg=st["avg"],
                   dist=[[b, counts.get(b, 0)] for b in BUCKETS], rows=rows)


@app.get("/api/reviews")
def api_reviews():
    """All leads in the rating range as JSON."""
    lo, hi = rating_range()
    rows = db.fetch(lo, hi)
    return jsonify(count=len(rows), rows=rows)


@app.get("/download/<kind>")
def download(kind):
    lo, hi = rating_range()
    rows = db.fetch(lo, hi)
    cols = ["review_id"] + db.COLUMNS + ["last_updated"]
    name = f"reviews_{lo}-{hi}"
    if kind == "csv":
        import csv
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        w.writerows([["" if r[c] is None else r[c] for c in cols] for r in rows])
        return send_file(io.BytesIO(buf.getvalue().encode("utf-8-sig")), mimetype="text/csv",
                         as_attachment=True, download_name=name + ".csv")
    from openpyxl import Workbook
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("reviews")
    ws.append(cols)
    for r in rows:
        ws.append(["" if r[c] is None else r[c] for c in cols])
    data = io.BytesIO()
    wb.save(data); data.seek(0)
    return send_file(data, as_attachment=True, download_name=name + ".xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/clear")
def api_clear():
    if JOB["state"] in ("starting", "running"):
        return jsonify(error="Stop the scrape first."), 409
    db.clear()
    if scraper is not None and os.path.exists(scraper.DONE_TXT):
        os.remove(scraper.DONE_TXT)
    JOB.update(state="idle", log=[], total=0, done=0, current="", reviews=0)
    return jsonify(ok=True)


INDEX_HTML = r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clutch Review Scraper</title>
<style>
:root{--bg:#f4f6fb;--card:#fff;--fg:#1c2333;--mut:#667085;--line:#e3e7ef;--acc:#2451e6;--acc2:#e8eefe;--ok:#12805c;--warn:#b7791f;--bad:#c53030}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 "Segoe UI",system-ui,sans-serif}
header{background:#101a3a;color:#fff;padding:18px 28px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}
header h1{margin:0;font-size:20px;font-weight:650}header p{margin:2px 0 0;color:#b8c3e6;font-size:13px}
.pill{padding:5px 14px;border-radius:999px;font-size:13px;font-weight:600;background:#2b3766;color:#dfe6ff}
.pill.running,.pill.starting{background:#1f5eff;color:#fff}.pill.finished{background:#12805c;color:#fff}.pill.error{background:#c53030;color:#fff}.pill.stopped{background:#b7791f;color:#fff}
main{max-width:1240px;margin:0 auto;padding:22px 20px 60px;display:grid;gap:18px}
.grid{display:grid;grid-template-columns:340px 1fr;gap:18px}@media(max-width:900px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}
.card h2{margin:0 0 12px;font-size:15px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
label{display:block;font-size:13px;font-weight:600;margin:12px 0 4px}input,select{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:8px;font:inherit;background:#fff;color:var(--fg)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
button{font:inherit;font-weight:600;padding:10px 16px;border-radius:8px;border:1px solid var(--line);background:#fff;cursor:pointer;color:var(--fg)}
button.primary{background:var(--acc);color:#fff;border-color:var(--acc)}button.danger{color:var(--bad)}button:disabled{opacity:.5;cursor:not-allowed}
.btns{display:flex;gap:8px;margin-top:16px;flex-wrap:wrap}.hint{font-size:12.5px;color:var(--mut);margin-top:10px}
.note{background:#fff8e6;border:1px solid #f1d98a;color:#7a5a06;padding:10px 12px;border-radius:8px;font-size:13px;margin-top:14px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}@media(max-width:700px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{background:var(--acc2);border-radius:10px;padding:12px 14px}.stat b{display:block;font-size:26px;line-height:1.1}.stat span{font-size:12.5px;color:var(--mut)}
.bar{height:10px;background:var(--line);border-radius:999px;overflow:hidden;margin:14px 0 6px}.bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .4s}
.prog{font-size:13px;color:var(--mut);display:flex;justify-content:space-between}
.dist{display:grid;gap:6px;margin-top:14px}.d{display:grid;grid-template-columns:64px 1fr 44px;align-items:center;gap:8px;font-size:13px}.d div{height:12px;background:var(--line);border-radius:6px;overflow:hidden}.d i{display:block;height:100%;background:var(--acc)}
pre{margin:0;background:#0f1424;color:#cfd8f6;border-radius:8px;padding:12px;height:170px;overflow:auto;font:12.5px/1.5 Consolas,Menlo,monospace;white-space:pre-wrap}
.tools{display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:12px}.tools>div{width:110px}.tools .sp{flex:1}
.tw{overflow:auto;border:1px solid var(--line);border-radius:8px;max-height:460px}table{border-collapse:collapse;width:100%;font-size:13.5px}
th{position:sticky;top:0;background:#f0f3fa;text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap}td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;max-width:280px}
.r{font-weight:700;color:var(--ok)}.empty{padding:28px;text-align:center;color:var(--mut)}
</style></head><body>
<header><div><h1>Clutch Review Scraper</h1><p>Collect company reviews from Clutch and filter them by rating</p></div><span id="pill" class="pill">Idle</span></header>
<main>
<div class="grid">
 <section class="card"><h2>Scrape settings</h2>
  <label>Clutch category</label>
  <select id="preset"><option value="https://clutch.co/developers">Software developers</option><option value="https://clutch.co/web-developers">Web developers</option><option value="https://clutch.co/web-designers">Web designers</option><option value="https://clutch.co/app-developers">Mobile app developers</option><option value="https://clutch.co/seo-firms">SEO firms</option><option value="https://clutch.co/agencies/digital-marketing">Digital marketing agencies</option><option value="https://clutch.co/it-services">IT services</option><option value="">Custom URL...</option></select>
  <input id="category" value="https://clutch.co/developers" style="margin-top:8px">
  <div class="row"><div><label>Companies</label><input id="mc" type="number" min="1" max="500" value="3"></div><div><label>Category pages</label><input id="mp" type="number" min="1" max="20" value="1"></div></div>
  <div class="btns"><button id="go" class="primary">Start scraping</button><button id="stop" disabled>Stop</button></div>
  <div class="note" id="nosc" style="display:none">Scraping is disabled on this server. Run <b>run_weekly.py</b> on a machine with Chrome; it pushes leads here.</div>
  <div class="note">A Chrome window opens during a run. If Clutch shows a "verify you are human" check, solve it in that window and the scraper continues.</div>
  <div class="hint">The scraper collects every review of each company. The rating filter below is applied to the results and downloads.</div>
 </section>
 <section class="card"><h2>Overview</h2>
  <div class="stats"><div class="stat"><b id="s1">0</b><span>Reviews collected</span></div><div class="stat"><b id="s2">0</b><span>Companies</span></div><div class="stat"><b id="s3">0</b><span>Match rating filter</span></div><div class="stat"><b id="s4">-</b><span>Average rating (filtered)</span></div></div>
  <div class="bar"><i id="bar"></i></div><div class="prog"><span id="ptxt">Ready</span><span id="pct">0%</span></div>
  <div class="dist" id="dist"></div>
 </section>
</div>
<section class="card"><h2>Live log</h2><pre id="log">Waiting to start...</pre></section>
<section class="card"><h2>Results</h2>
 <div class="tools">
  <div><label>Min rating</label><input id="lo" type="number" min="0" max="5" step="0.1" value="5"></div>
  <div><label>Max rating</label><input id="hi" type="number" min="0" max="5" step="0.1" value="5"></div>
  <button id="apply">Apply filter</button><span class="sp"></span>
  <button id="csv">Download CSV</button><button id="xlsx" class="primary">Download Excel</button><button id="clear" class="danger">Clear data</button>
 </div>
 <div class="tw"><table><thead><tr><th>Company</th><th>Review</th><th>Rating</th><th>Date</th><th>Reviewer</th><th>Position</th><th>Industry</th><th>Location</th></tr></thead><tbody id="rows"></tbody></table></div>
 <div class="hint" id="cap"></div>
</section>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const qs=()=>`min=${encodeURIComponent($('lo').value||0)}&max=${encodeURIComponent($('hi').value||5)}`;
$('preset').onchange=()=>{if($('preset').value)$('category').value=$('preset').value;else{$('category').value='https://clutch.co/';$('category').focus();}};
$('go').onclick=async()=>{
  const r=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({category:$('category').value,max_companies:+$('mc').value,max_dir_pages:+$('mp').value})});
  const j=await r.json(); if(!r.ok) alert(j.error); poll();
};
$('stop').onclick=()=>fetch('/api/stop',{method:'POST'});
$('apply').onclick=loadResults;
$('csv').onclick=()=>location.href='/download/csv?'+qs();
$('xlsx').onclick=()=>location.href='/download/xlsx?'+qs();
$('clear').onclick=async()=>{if(!confirm('Delete all collected reviews?'))return;const r=await fetch('/api/clear',{method:'POST'});const j=await r.json();if(!r.ok)alert(j.error);loadResults();poll();};
let last='';
async function poll(){
  try{
    const s=await (await fetch('/api/status')).json();
    const busy=s.state==='running'||s.state==='starting';
    const p=$('pill');p.textContent=s.state[0].toUpperCase()+s.state.slice(1);p.className='pill '+s.state;
    $('go').disabled=busy||!s.scraper_enabled;$('stop').disabled=!busy;$('nosc').style.display=s.scraper_enabled?'none':'block';
    const pct=s.total?Math.round(100*s.done/s.total):0;$('bar').style.width=pct+'%';$('pct').textContent=pct+'%';
    $('ptxt').textContent=busy?(s.total?`Company ${Math.min(s.done+1,s.total)} of ${s.total}${s.current?' ('+s.current+')':''}`:'Starting browser...'):(s.state==='idle'?'Ready':`${s.done} of ${s.total} companies done`);
    if(s.log.length){const el=$('log'),txt=s.log.join('\n');if(txt!==last){const bottom=el.scrollTop+el.clientHeight>=el.scrollHeight-20;el.textContent=txt;if(bottom)el.scrollTop=el.scrollHeight;last=txt;}}
    if(busy)loadResults();
    setTimeout(poll,busy?1500:4000);
  }catch(e){setTimeout(poll,4000);}
}
async function loadResults(){
  const d=await (await fetch('/api/results?'+qs())).json();
  $('s1').textContent=d.total;$('s2').textContent=d.companies;$('s3').textContent=d.matching;$('s4').textContent=d.avg??'-';
  const mx=Math.max(1,...d.dist.map(x=>x[1]));
  $('dist').innerHTML=d.dist.map(([k,v])=>`<div class="d"><span>${k}</span><div><i style="width:${100*v/mx}%"></i></div><span>${v}</span></div>`).join('');
  $('rows').innerHTML=d.rows.length?d.rows.map(r=>`<tr><td>${esc(r.company)}</td><td>${esc(r.review_title)}</td><td class="r">${esc(r.rating)}</td><td>${esc(r.review_date)}</td><td>${esc(r.reviewer_name)}</td><td>${esc(r.reviewer_position)}</td><td>${esc(r.industry)}</td><td>${esc(r.location)}</td></tr>`).join(''):'<tr><td colspan="8" class="empty">No reviews match yet. Start a scrape or change the rating filter.</td></tr>';
  $('cap').textContent=d.matching>d.rows.length?`Showing the first ${d.rows.length} of ${d.matching} matching reviews. Downloads contain all of them.`:'';
}
loadResults();poll();
</script></body></html>'''


if __name__ == "__main__":
    # Local use only. On cPanel, Passenger loads passenger_wsgi.py instead.
    host = os.environ.get("CLUTCH_HOST", "127.0.0.1")
    if not os.environ.get("CLUTCH_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host=host, port=5000, debug=False)
