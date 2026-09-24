#!/usr/bin/env python3
"""MeteorRadio ML labelling and review UI (default port 8101)."""

from __future__ import annotations

import html
import json
import mimetypes
import os
import time
import urllib.parse
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from ml_common import (
    IMAGE_URL,
    LABELS_FILE,
    MODEL_FILE,
    PREDICTIONS_FILE,
    RADAR,
    VALID_LABELS,
    atomic_json,
    dataset_csv_bytes,
    extract_features,
    fetch_classification,
    find_smp_path,
    radar_file_map,
    load_labels,
    load_model,
    load_predictions,
    predict_features,
    read_scores,
    safe_name,
    utc_timestamp,
)

HOST = os.environ.get("MR_ML_HOST", "0.0.0.0")
PORT = int(os.environ.get("MR_ML_PORT", "8101"))


def model_public(model: Any) -> Dict[str, Any]:
    if not isinstance(model, dict):
        return {"available": False}
    return {
        "available": True,
        "model_id": model.get("model_id"),
        "created_utc": model.get("created_utc"),
        "classes": model.get("classes"),
        "unknown_threshold": model.get("unknown_threshold"),
        "training": model.get("training"),
    }


def snapshot() -> Dict[str, Any]:
    scores = read_scores()
    labels_payload = load_labels()
    predictions_payload = load_predictions()
    labels = labels_payload.get("labels", {})
    predictions = predictions_payload.get("items", {})
    items = []

    radar_files = radar_file_map()
    for name, score in scores.items():
        path = radar_files.get(name)
        if path is None or not path.is_file():
            continue
        try:
            st = path.stat()
            mtime = st.st_mtime
            size = st.st_size
        except OSError:
            continue
        label_entry = labels.get(name) if isinstance(labels, dict) else None
        prediction = predictions.get(name) if isinstance(predictions, dict) else None
        items.append(
            {
                "file": name,
                "score": score,
                "mtime": mtime,
                "bytes": size,
                "label": label_entry.get("label") if isinstance(label_entry, dict) else None,
                "labeled_at": label_entry.get("labeled_at") if isinstance(label_entry, dict) else None,
                "prediction": prediction if isinstance(prediction, dict) else None,
            }
        )

    items.sort(key=lambda x: x["mtime"], reverse=True)
    label_counts = Counter(
        entry.get("label")
        for entry in labels.values()
        if isinstance(entry, dict) and entry.get("label") in VALID_LABELS
    ) if isinstance(labels, dict) else Counter()

    return {
        "ok": True,
        "service": "meteorradio-ml",
        "version": 1,
        "items": items,
        "total": len(items),
        "unlabeled": sum(1 for item in items if not item["label"]),
        "label_counts": dict(label_counts),
        "model": model_public(load_model()),
        "paths": {
            "labels": str(LABELS_FILE),
            "model": str(MODEL_FILE),
            "predictions": str(PREDICTIONS_FILE),
        },
    }


def set_label(name: str, label: str) -> Dict[str, Any]:
    name = safe_name(name)
    if label not in VALID_LABELS:
        raise ValueError("invalid label")
    src = find_smp_path(name)
    if src is None or not src.is_file():
        raise FileNotFoundError(name)

    scores = read_scores()
    score = scores.get(name)
    heuristic = None
    feature_vector = None
    heuristic_error = None
    try:
        heuristic = fetch_classification(name)
        feature_vector = extract_features(heuristic)
    except Exception as exc:
        heuristic_error = repr(exc)

    payload = load_labels()
    labels = payload.get("labels", {})
    if not isinstance(labels, dict):
        labels = {}

    st = src.stat()
    entry = {
        "label": label,
        "labeled_at": utc_timestamp(),
        "heuristic_score": score,
        "heuristic_version": heuristic.get("heuristic_version") if isinstance(heuristic, dict) else None,
        "feature_vector": feature_vector,
        "heuristic": heuristic,
        "heuristic_error": heuristic_error,
        "source_file_mtime": st.st_mtime,
        "source_file_bytes": st.st_size,
        "reviewer": "local-manual",
    }

    model = load_model()
    if model and feature_vector:
        try:
            entry["model_at_label_time"] = predict_features(model, feature_vector)
        except Exception as exc:
            entry["model_at_label_time_error"] = repr(exc)

    labels[name] = entry
    payload = {
        "version": 1,
        "updated": utc_timestamp(),
        "labels": labels,
    }
    atomic_json(LABELS_FILE, payload)
    return {"ok": True, "file": name, "label": label, "entry": entry}


def clear_label(name: str) -> Dict[str, Any]:
    name = safe_name(name)
    payload = load_labels()
    labels = payload.get("labels", {})
    if isinstance(labels, dict):
        labels.pop(name, None)
    atomic_json(
        LABELS_FILE,
        {"version": 1, "updated": utc_timestamp(), "labels": labels},
    )
    return {"ok": True, "file": name, "label": None}


HTML = r'''<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MeteorRadio ML Review</title>
<style>
:root{color-scheme:dark}body{margin:0;background:#0c1117;color:#d7e0e8;font:14px system-ui,-apple-system,sans-serif}.top{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:12px 16px;background:#121a23;border-bottom:1px solid #283443;position:sticky;top:0;z-index:3}.top b{font-size:17px}.pill{padding:4px 8px;border:1px solid #35465a;border-radius:999px;color:#b7c8d8}.wrap{max-width:1500px;margin:auto;padding:14px}.grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(320px,.55fr);gap:14px}@media(max-width:900px){.grid{grid-template-columns:1fr}}.card{background:#111923;border:1px solid #2a3949;border-radius:10px;padding:12px}.imagebox{background:#05080b;min-height:430px;display:flex;align-items:center;justify-content:center;border-radius:8px;overflow:hidden}.imagebox img{display:block;max-width:100%;max-height:72vh}.file{font-family:ui-monospace,SFMono-Regular,monospace;word-break:break-all;color:#9cc7ee}.score{font-size:32px;font-weight:800}.prediction{font-size:20px;font-weight:700}.prob{font-family:ui-monospace,SFMono-Regular,monospace;white-space:pre-wrap;color:#b8c8d7}.buttons{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:12px}@media(max-width:700px){.buttons{grid-template-columns:1fr 1fr}}button{border:1px solid #40556b;background:#182433;color:#e4edf5;border-radius:8px;padding:12px 8px;font-weight:700;cursor:pointer}button:hover{background:#223348}.meteor{border-color:#2b8650}.aircraft{border-color:#a77729}.satellite{border-color:#5278b8}.rfi{border-color:#a5444c}.unknown{border-color:#666}.nav{display:flex;gap:8px;margin-top:10px}.nav button{flex:1}.muted{color:#8293a3}.counts{display:grid;grid-template-columns:1fr 1fr;gap:5px}.status{margin-top:8px;padding:8px;border-radius:6px;background:#0b1219}.error{color:#ff9299}.ok{color:#8ee6a8}kbd{background:#252f3a;border:1px solid #445161;border-radius:4px;padding:1px 5px}.bar{height:6px;background:#233141;border-radius:999px;overflow:hidden;margin:2px 0 8px}.bar>i{display:block;height:100%;background:#7eb2df}.mode{margin-left:auto}select{background:#101820;color:#d7e0e8;border:1px solid #40556b;border-radius:6px;padding:6px}.links a{color:#8ec8ff;margin-right:12px}
</style>
</head>
<body>
<div class="top"><b>MeteorRadio ML Review</b><span class="pill" id="summary">ładowanie…</span><span class="pill" id="model">model…</span><span class="mode">Widok: <select id="mode"><option value="unlabeled">nieopisane</option><option value="all">wszystkie</option></select></span></div>
<div class="wrap">
<div class="grid">
<div class="card"><div class="imagebox"><img id="img" alt="waterfall"></div><div class="buttons"><button class="meteor" data-label="meteor"><kbd>M</kbd> METEOR</button><button class="aircraft" data-label="aircraft"><kbd>A</kbd> AIRCRAFT</button><button class="satellite" data-label="satellite"><kbd>S</kbd> SATELLITE</button><button class="rfi" data-label="rfi"><kbd>R</kbd> RFI</button><button class="unknown" data-label="unknown"><kbd>U</kbd> UNKNOWN</button></div><div class="nav"><button id="prev">← poprzednia</button><button id="clear">usuń etykietę</button><button id="next">następna →</button></div><div id="status" class="status muted">Gotowy.</div></div>
<div class="card"><div class="file" id="file">—</div><div style="display:flex;gap:20px;align-items:end;margin:12px 0"><div><div class="muted">score heurystyczny</div><div class="score" id="score">—</div></div><div><div class="muted">etykieta ręczna</div><div class="prediction" id="label">—</div></div></div><hr style="border-color:#263545"><div class="muted">ML</div><div class="prediction" id="pred">brak modelu / predykcji</div><div class="prob" id="prob"></div><hr style="border-color:#263545"><div class="counts" id="counts"></div><div class="links" style="margin-top:14px"><a href="/api/export.csv">eksport dataset CSV</a><a href="/healthz">health</a></div><p class="muted">Skróty: M meteor, A samolot, S satelita, R RFI, U unknown, ←/→ nawigacja. Etykieta zapisuje również snapshot aktualnych cech v5.6.2, więc trening nie zależy od późniejszej retencji pliku SMP.</p></div>
</div></div>
<script>
'use strict';
let all=[], items=[], idx=0, meta=null;
const $=id=>document.getElementById(id);
function esc(s){return String(s??'')}
function filtered(){const mode=$('mode').value;return mode==='all'?all:all.filter(x=>!x.label)}
function probs(p){if(!p||!p.probabilities)return '';return Object.entries(p.probabilities).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`${k.padEnd(10)} ${(v*100).toFixed(1)}%`).join('\n')}
function render(){items=filtered();if(!items.length){$('file').textContent='Brak detekcji w tym widoku';$('img').removeAttribute('src');$('score').textContent='—';$('label').textContent='—';$('pred').textContent='—';$('prob').textContent='';return}idx=Math.max(0,Math.min(idx,items.length-1));const x=items[idx];$('file').textContent=`${idx+1}/${items.length}  ${x.file}`;$('img').src='/image?file='+encodeURIComponent(x.file)+'&t='+Date.now();$('score').textContent=(x.score??'—')+'/7';$('label').textContent=x.label||'nieopisane';const p=x.prediction;$('pred').textContent=p?`${p.predicted_label}  ${(100*(p.confidence||0)).toFixed(1)}%`:'brak predykcji';$('prob').textContent=probs(p);}
async function load(){const r=await fetch('/api/data',{cache:'no-store'});meta=await r.json();all=meta.items||[];$('summary').textContent=`bieżące ${meta.total} · nieopisane ${meta.unlabeled}`;const m=meta.model||{};$('model').textContent=m.available?`${m.model_id} · próg UNKNOWN ${Math.round(100*m.unknown_threshold)}%`:'model: jeszcze brak';const counts=meta.label_counts||{};$('counts').innerHTML=['meteor','aircraft','satellite','rfi','unknown'].map(k=>`<div>${k}</div><div><b>${counts[k]||0}</b></div>`).join('');idx=0;render()}
async function label(value){if(!items.length)return;const x=items[idx];$('status').textContent=`Zapisuję ${value}…`;try{const r=await fetch('/api/label',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:x.file,label:value})});const d=await r.json();if(!d.ok)throw new Error(d.error||'błąd');$('status').textContent=`Zapisano: ${value}`;await load()}catch(e){$('status').textContent='Błąd: '+e;$('status').className='status error'}}
async function clearLabel(){if(!items.length)return;const x=items[idx];const r=await fetch('/api/unlabel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:x.file})});const d=await r.json();$('status').textContent=d.ok?'Etykieta usunięta':'Błąd: '+(d.error||'');await load()}
document.querySelectorAll('[data-label]').forEach(b=>b.onclick=()=>label(b.dataset.label));$('prev').onclick=()=>{idx=Math.max(0,idx-1);render()};$('next').onclick=()=>{idx=Math.min(items.length-1,idx+1);render()};$('clear').onclick=clearLabel;$('mode').onchange=()=>{idx=0;render()};document.addEventListener('keydown',e=>{if(e.target.tagName==='SELECT')return;const k=e.key.toLowerCase();if(k==='m')label('meteor');else if(k==='a')label('aircraft');else if(k==='s')label('satellite');else if(k==='r')label('rfi');else if(k==='u')label('unknown');else if(e.key==='ArrowRight'){$('next').click()}else if(e.key==='ArrowLeft'){$('prev').click()}});load().catch(e=>{$('status').textContent='Błąd startu: '+e;$('status').className='status error'});
</script>
</body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "MeteorRadioML/1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(time.strftime("%Y-%m-%d %H:%M:%S"), self.address_string(), fmt % args, flush=True)

    def send_bytes(self, raw: bytes, content_type: str, status: int = 200, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, payload: Any, status: int = 200) -> None:
        self.send_bytes(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except Exception:
            length = 0
        if not (1 <= length <= 16384):
            raise ValueError("invalid body length")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON object expected")
        return data

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/":
                return self.send_bytes(HTML.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/healthz":
                model = load_model()
                return self.send_json({"ok": True, "service": "meteorradio-ml", "port": PORT, "model_id": model.get("model_id") if model else None})
            if path == "/api/data":
                return self.send_json(snapshot())
            if path == "/api/export.csv":
                return self.send_bytes(dataset_csv_bytes(), "text/csv; charset=utf-8", cache="private, max-age=5")
            if path == "/api/features":
                name = safe_name((query.get("file") or [""])[0])
                classification = fetch_classification(name)
                features = extract_features(classification)
                model = load_model()
                prediction = predict_features(model, features) if model else None
                return self.send_json({"ok": True, "file": name, "classification": classification, "feature_vector": features, "prediction": prediction})
            if path == "/image":
                name = safe_name((query.get("file") or [""])[0])
                request = urllib.request.Request(
                    IMAGE_URL + "?" + urllib.parse.urlencode({"file": name}),
                    headers={"User-Agent": "MeteorRadio-ML/1"},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read()
                    content_type = response.headers.get("Content-Type") or "image/png"
                return self.send_bytes(raw, content_type, cache="private, max-age=30")
            self.send_error(404)
        except ValueError as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
        except FileNotFoundError as exc:
            self.send_json({"ok": False, "error": str(exc)}, 404)
        except Exception as exc:
            print("GET_ERROR", path, repr(exc), flush=True)
            self.send_json({"ok": False, "error": repr(exc)}, 500)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/label":
                return self.send_json(set_label(payload.get("file"), payload.get("label")))
            if path == "/api/unlabel":
                return self.send_json(clear_label(payload.get("file")))
            self.send_json({"ok": False, "error": "not found"}, 404)
        except ValueError as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
        except FileNotFoundError as exc:
            self.send_json({"ok": False, "error": str(exc)}, 404)
        except Exception as exc:
            print("POST_ERROR", path, repr(exc), flush=True)
            self.send_json({"ok": False, "error": repr(exc)}, 500)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MeteorRadio ML Review listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
