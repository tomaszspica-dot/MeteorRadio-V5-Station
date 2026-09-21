#!/usr/bin/env python3

import json
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np


ROOT = Path("/home/pi/radar_data").resolve()
HOST = "0.0.0.0"
PORT = 8099
MAX_EVENTS = 250


HTML = r"""<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MeteorRadio 3D Viewer</title>

<style>
:root{
  color-scheme:dark;
  --bg:#07111c;
  --panel:#0c1c2c;
  --line:#1d4664;
  --fg:#e8f3fb;
  --muted:#8ca9bd;
  --accent:#31c7ff;
}
*{box-sizing:border-box}

body{
  margin:0;
  background:var(--bg);
  color:var(--fg);
  font:14px system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}

header{
  min-height:58px;
  padding:13px 18px;
  border-bottom:1px solid var(--line);
  display:flex;
  gap:12px;
  align-items:center;
  flex-wrap:wrap;
}

h1{
  margin:0;
  font-size:18px;
}

.pill{
  border:1px solid var(--line);
  border-radius:999px;
  padding:4px 9px;
  color:var(--muted);
}

main{
  display:grid;
  grid-template-columns:350px 1fr;
  height:calc(100vh - 58px);
  min-height:560px;
}

aside{
  border-right:1px solid var(--line);
  padding:14px;
  overflow:auto;
}

.view{
  min-width:0;
  position:relative;
}

label{
  display:block;
  margin:11px 0 5px;
  color:var(--muted);
}

select,button{
  background:#10263a;
  color:var(--fg);
  border:1px solid var(--line);
  border-radius:7px;
  padding:8px;
}

select{
  width:100%;
}

button{
  cursor:pointer;
}

button:hover{
  border-color:var(--accent);
}

.row{
  display:flex;
  gap:8px;
  align-items:center;
}

.meta{
  margin-top:15px;
  padding-top:10px;
  border-top:1px solid var(--line);
}

.kv{
  display:grid;
  grid-template-columns:128px 1fr;
  gap:5px 8px;
  margin:4px 0;
  overflow-wrap:anywhere;
}

.k{
  color:var(--muted);
}

#canvas{
  display:block;
  width:100%;
  height:100%;
  cursor:grab;
  background:
    radial-gradient(circle at 50% 45%,#10283b 0,#06101a 68%);
}

#canvas:active{
  cursor:grabbing;
}

.overlay{
  position:absolute;
  left:12px;
  top:12px;
  background:#07111cdd;
  border:1px solid var(--line);
  border-radius:8px;
  padding:8px 10px;
  pointer-events:none;
}

.axes{
  position:absolute;
  right:12px;
  bottom:12px;
  max-width:420px;
  color:var(--muted);
  background:#07111cdd;
  border:1px solid var(--line);
  border-radius:8px;
  padding:7px 9px;
}

.status{
  margin-top:11px;
  color:var(--muted);
}


.cursorInfo{
  position:absolute;
  display:none;
  z-index:50;
  pointer-events:none;
  padding:7px 9px;
  border:1px solid #3a789d;
  border-radius:7px;
  background:rgba(4,12,20,.95);
  color:#eaf6ff;
  font-size:12px;
  line-height:1.4;
  white-space:nowrap;
  box-shadow:0 4px 14px rgba(0,0,0,.4);
}

.err{
  color:#ff9a9a;
}

@media(max-width:800px){
  main{
    grid-template-columns:1fr;
    grid-template-rows:auto 65vh;
    height:auto;
  }

  aside{
    border-right:0;
    border-bottom:1px solid var(--line);
  }
}
</style>
</head>

<body>

<header>
  <h1>MeteorRadio 3D Spectrogram Viewer</h1>
  <span class="pill">NPZ — tylko odczyt</span>
  <span class="pill">GRAVES 143,050 MHz</span>
</header>

<main>

<aside>

<label>Detekcja</label>
<select id="event"></select>

<label>Zakres Dopplera</label>
<div class="row">
  <select id="span">
    <option value="300" selected>±300 Hz</option>
    <option value="600">±600 Hz</option>
    <option value="1200">±1200 Hz</option>
    <option value="3000">±3000 Hz</option>
  </select>
  <button id="load">Wczytaj</button>
</div>

<label>Rozdzielczość analizy</label>
<select id="fft">
  <option value="2048">2048 — zgodna z panelem (18,31 Hz)</option>
  <option value="4096" selected>4096 — HQ (9,16 Hz)</option>
  <option value="8192">8192 — MAX (4,58 Hz)</option>
</select>

<label>Widok tych samych danych</label>
<div class="row">
  <button id="reset">3D</button>
  <button id="top">2D waterfall</button>
</div>

<div class="meta" id="meta"></div>
<div class="status" id="status">Ładowanie listy detekcji…</div>

</aside>

<section class="view">
  <canvas id="canvas"></canvas>

  <div class="overlay">
    przeciągnij = obrót • kółko = zoom • dwuklik = reset
  </div>

  <div class="axes">
    X: Doppler [Hz] • Y: czas [s] • wysokość i kolor: moc względna [dB]
  </div>

  <div id="cursorInfo" class="cursorInfo"></div>
</section>

</main>

<script>
const $ = s => document.querySelector(s);

const canvas = $("#canvas");
const ctx = canvas.getContext("2d");

let S = null;
let viewMode = "3d";
let hover3DPoints = [];

let yaw   = -0.75;
let pitch =  0.72;
let zoom  =  1.00;

let dragging = false;
let lastX = 0;
let lastY = 0;


function escapeHtml(value){
  return String(value ?? "").replace(/[&<>"]/g, c => ({
    "&":"&amp;",
    "<":"&lt;",
    ">":"&gt;",
    '"':"&quot;"
  }[c]));
}


function resize(){
  const r = canvas.getBoundingClientRect();
  const d = Math.min(window.devicePixelRatio || 1, 2);

  canvas.width  = Math.max(1, Math.floor(r.width  * d));
  canvas.height = Math.max(1, Math.floor(r.height * d));

  ctx.setTransform(d,0,0,d,0,0);

  render();
}


function colorMap(t){

  t = Math.max(
    0,
    Math.min(
      1,
      t
    )
  );

  const stops = [
    [0.00,   0,   0,   4],
    [0.10,  22,  11,  57],
    [0.20,  66,  10, 104],
    [0.30, 106,  23, 110],
    [0.40, 147,  38, 103],
    [0.50, 188,  55,  84],
    [0.60, 221,  81,  58],
    [0.70, 243, 120,  25],
    [0.80, 252, 165,  10],
    [0.90, 246, 215,  70],
    [1.00, 252, 255, 164]
  ];

  for(let i=0;i<stops.length-1;i++){

    const A = stops[i];
    const B = stops[i+1];

    if(t >= A[0] && t <= B[0]){

      const u =
        (t-A[0])
        /
        (B[0]-A[0]);

      const r =
        A[1]
        + (B[1]-A[1])*u;

      const g =
        A[2]
        + (B[2]-A[2])*u;

      const b =
        A[3]
        + (B[3]-A[3])*u;

      return `rgb(${r|0},${g|0},${b|0})`;
    }
  }

  return "rgb(252,255,164)";
}

function project(x,y,z,w,h){

  const cy = Math.cos(yaw);
  const sy = Math.sin(yaw);

  const cp = Math.cos(pitch);
  const sp = Math.sin(pitch);

  let x1 = x*cy - y*sy;
  let y1 = x*sy + y*cy;
  let z1 = z;

  let y2 = y1*cp - z1*sp;
  let z2 = y1*sp + z1*cp;

  const camera = 4.2;
  const perspective = (1.55 * zoom) / (camera - z2);
  const scale = Math.min(w,h) * 1.55;

  return [
    w/2 + x1*perspective*scale,
    h/2 - y2*perspective*scale,
    z2
  ];
}


function renderHeatmap(){

  const w = canvas.clientWidth;
  const h = canvas.clientHeight;

  ctx.clearRect(0,0,w,h);

  if(!S || !S.z || !S.z.length)
    return;

  const nt = S.z.length;
  const nf = S.z[0].length;

  const left   = 62;
  const right  = 18;
  const top    = 18;
  const bottom = 42;

  const pw = w-left-right;
  const ph = h-top-bottom;

  const zmin = S.z_floor;
  const zmax = S.z_ceil;
  const dz = Math.max(0.1,zmax-zmin);

  ctx.fillStyle = "rgb(0,0,4)";
  ctx.fillRect(left,top,pw,ph);

  const cw = pw/nt;
  const ch = ph/nf;

  for(let ti=0;ti<nt;ti++){

    for(let fi=0;fi<nf;fi++){

      const v =
        (S.z[ti][fi]-zmin)/dz;

      ctx.fillStyle =
        colorMap(v);

      const x =
        left + ti*cw;

      const y =
        top + (nf-1-fi)*ch;

      ctx.fillRect(
        x,
        y,
        Math.ceil(cw+0.4),
        Math.ceil(ch+0.4)
      );
    }
  }


  // ==========================================================
  // PEAK DOPPLER
  // ==========================================================

  const peak =
    Number(S.meta.peak_freq_hz);

  const f0 =
    S.freq_hz[0];

  const f1 =
    S.freq_hz[
      S.freq_hz.length-1
    ];

  if(
    Number.isFinite(peak)
    && peak >= f0
    && peak <= f1
  ){

    const u =
      (peak-f0)/(f1-f0);

    const y =
      top + (1-u)*ph;

    ctx.strokeStyle =
      "rgba(55,220,255,1)";

    ctx.lineWidth = 2;

    ctx.setLineDash([8,5]);

    ctx.beginPath();
    ctx.moveTo(left,y);
    ctx.lineTo(left+pw,y);
    ctx.stroke();

    ctx.setLineDash([]);

    ctx.fillStyle =
      "rgba(80,230,255,1)";

    ctx.font =
      "12px system-ui";

    ctx.textAlign =
      "right";

    ctx.fillText(
      "PEAK "
      + peak.toFixed(1)
      + " Hz",
      left+pw-6,
      y-6
    );
  }


  // ==========================================================
  // RAMKA
  // ==========================================================

  ctx.strokeStyle =
    "rgba(160,190,215,.65)";

  ctx.lineWidth = 1;

  ctx.strokeRect(
    left,
    top,
    pw,
    ph
  );


  // ==========================================================
  // OŚ CZASU
  // ==========================================================

  ctx.fillStyle =
    "#9db7c9";

  ctx.font =
    "12px system-ui";

  ctx.textAlign =
    "center";

  for(let i=0;i<=5;i++){

    const u = i/5;

    const x =
      left + u*pw;

    const t =
      S.time_s[0]
      + u*
      (
        S.time_s[
          S.time_s.length-1
        ]
        - S.time_s[0]
      );

    ctx.fillText(
      t.toFixed(1)+" s",
      x,
      h-18
    );
  }


  // ==========================================================
  // OŚ DOPPLERA
  // ==========================================================

  ctx.textAlign =
    "right";

  const ticks = [
    -300,
    -200,
    -100,
    0,
    100,
    200,
    300
  ];

  for(const f of ticks){

    if(f < f0 || f > f1)
      continue;

    const u =
      (f-f0)/(f1-f0);

    const y =
      top + (1-u)*ph;

    ctx.fillText(
      f+" Hz",
      left-7,
      y+4
    );
  }
}

function render3D(){

  const w = canvas.clientWidth;
  const h = canvas.clientHeight;

  ctx.clearRect(0,0,w,h);

  if(!S || !S.z || !S.z.length)
    return;

  const nt = S.z.length;
  const nf = S.z[0].length;

  const zmin = S.z_floor;
  const zmax = S.z_ceil;
  const dz = Math.max(0.1,zmax-zmin);

  const cells=[];

  hover3DPoints=[];


  // ==========================================================
  // POWIERZCHNIA
  // ==========================================================

  for(let i=0;i<nt-1;i++){

    const y0 =
      -1 + 2*i/(nt-1);

    const y1 =
      -1 + 2*(i+1)/(nt-1);

    for(let j=0;j<nf-1;j++){

      const x0 =
        -1 + 2*j/(nf-1);

      const x1 =
        -1 + 2*(j+1)/(nf-1);

      const a =
        Math.max(
          0,
          Math.min(
            1,
            (S.z[i][j]-zmin)/dz
          )
        );

      const b =
        Math.max(
          0,
          Math.min(
            1,
            (S.z[i][j+1]-zmin)/dz
          )
        );

      const c =
        Math.max(
          0,
          Math.min(
            1,
            (S.z[i+1][j+1]-zmin)/dz
          )
        );

      const d =
        Math.max(
          0,
          Math.min(
            1,
            (S.z[i+1][j]-zmin)/dz
          )
        );

      const za = a*0.95-0.38;
      const zb = b*0.95-0.38;
      const zc = c*0.95-0.38;
      const zd = d*0.95-0.38;

      const p0 =
        project(x0,y0,za,w,h);

      const p1 =
        project(x1,y0,zb,w,h);

      const p2 =
        project(x1,y1,zc,w,h);

      const p3 =
        project(x0,y1,zd,w,h);

      cells.push({

        p:[
          p0,
          p1,
          p2,
          p3
        ],

        depth:
          (
            p0[2]
            + p1[2]
            + p2[2]
            + p3[2]
          )/4,

        value:
          (a+b+c+d)/4
      });
    }
  }

  cells.sort(
    (a,b) =>
      a.depth-b.depth
  );

  ctx.lineWidth =
    0.18;

  for(const cell of cells){

    ctx.beginPath();

    ctx.moveTo(
      cell.p[0][0],
      cell.p[0][1]
    );

    ctx.lineTo(
      cell.p[1][0],
      cell.p[1][1]
    );

    ctx.lineTo(
      cell.p[2][0],
      cell.p[2][1]
    );

    ctx.lineTo(
      cell.p[3][0],
      cell.p[3][1]
    );

    ctx.closePath();

    ctx.fillStyle =
      colorMap(cell.value);

    ctx.fill();

    ctx.strokeStyle =
      "rgba(0,0,0,.08)";

    ctx.stroke();
  }


  // ==========================================================
  // PEAK DOPPLER — LINIA WZDŁUŻ CZASU
  // ==========================================================

  const peak =
    Number(S.meta.peak_freq_hz);

  const f0 =
    S.freq_hz[0];

  const f1 =
    S.freq_hz[
      S.freq_hz.length-1
    ];

  if(
    Number.isFinite(peak)
    && peak >= f0
    && peak <= f1
  ){

    const u =
      (peak-f0)/(f1-f0);

    const x =
      -1 + 2*u;

    const a =
      project(
        x,
        -1,
        -0.385,
        w,
        h
      );

    const b =
      project(
        x,
        1,
        -0.385,
        w,
        h
      );

    ctx.strokeStyle =
      "rgba(65,225,255,1)";

    ctx.lineWidth =
      2.2;

    ctx.setLineDash(
      [8,5]
    );

    ctx.beginPath();

    ctx.moveTo(
      a[0],
      a[1]
    );

    ctx.lineTo(
      b[0],
      b[1]
    );

    ctx.stroke();

    ctx.setLineDash([]);

    ctx.fillStyle =
      "rgba(90,235,255,1)";

    ctx.font =
      "12px system-ui";

    ctx.textAlign =
      "left";

    ctx.fillText(
      "PEAK "
      + peak.toFixed(1)
      + " Hz",
      b[0]+6,
      b[1]-6
    );
  }


  // ==========================================================
  // CACHE DLA HOVER
  // ==========================================================

  const stepT =
    Math.max(
      1,
      Math.ceil(nt/170)
    );

  const stepF =
    Math.max(
      1,
      Math.ceil(nf/90)
    );

  for(
    let i=0;
    i<nt;
    i+=stepT
  ){

    const y =
      -1 + 2*i/(nt-1);

    for(
      let j=0;
      j<nf;
      j+=stepF
    ){

      const x =
        -1 + 2*j/(nf-1);

      const v =
        Math.max(
          0,
          Math.min(
            1,
            (S.z[i][j]-zmin)/dz
          )
        );

      const z =
        v*0.95-0.38;

      const q =
        project(
          x,
          y,
          z,
          w,
          h
        );

      hover3DPoints.push(
        [
          q[0],
          q[1],
          i,
          j
        ]
      );
    }
  }
}

function render(){

  if(
    viewMode === "2d"
  )
    renderHeatmap();
  else
    render3D();
}


function hideCursorInfo(){

  const box =
    $("#cursorInfo");

  if(box)
    box.style.display =
      "none";
}


function showCursorInfo(
  px,
  py,
  ti,
  fi
){

  if(
    !S
    || ti < 0
    || fi < 0
    || ti >= S.z.length
    || fi >= S.z[0].length
  ){
    hideCursorInfo();
    return;
  }

  const t =
    Number(
      S.time_s[ti]
    );

  const f =
    Number(
      S.freq_hz[fi]
    );

  const db =
    Number(
      S.z[ti][fi]
    );

  const box =
    $("#cursorInfo");

  box.innerHTML =
    "<b>"
    + t.toFixed(3)
    + " s</b>"
    + "<br>Doppler: "
    + f.toFixed(1)
    + " Hz"
    + "<br>Moc ponad tło: "
    + db.toFixed(1)
    + " dB";

  box.style.display =
    "block";

  box.style.left =
    Math.max(
      5,
      Math.min(
        px+14,
        canvas.clientWidth-175
      )
    )
    + "px";

  box.style.top =
    Math.max(
      5,
      Math.min(
        py+14,
        canvas.clientHeight-82
      )
    )
    + "px";
}


function updateHover(e){

  if(
    !S
    || dragging
  ){
    hideCursorInfo();
    return;
  }

  const rect =
    canvas.getBoundingClientRect();

  const px =
    e.clientX
    - rect.left;

  const py =
    e.clientY
    - rect.top;


  // ==========================================================
  // 2D
  // ==========================================================

  if(viewMode === "2d"){

    const w =
      canvas.clientWidth;

    const h =
      canvas.clientHeight;

    const left   = 62;
    const right  = 18;
    const top    = 18;
    const bottom = 42;

    const pw =
      w-left-right;

    const ph =
      h-top-bottom;

    if(
      px < left
      || px > left+pw
      || py < top
      || py > top+ph
    ){
      hideCursorInfo();
      return;
    }

    let ti =
      Math.round(
        (
          px-left
        )/pw
        * (
          S.z.length-1
        )
      );

    let fi =
      Math.round(
        (
          1
          - (py-top)/ph
        )
        * (
          S.z[0].length-1
        )
      );

    ti =
      Math.max(
        0,
        Math.min(
          S.z.length-1,
          ti
        )
      );

    fi =
      Math.max(
        0,
        Math.min(
          S.z[0].length-1,
          fi
        )
      );

    showCursorInfo(
      px,
      py,
      ti,
      fi
    );

    return;
  }


  // ==========================================================
  // 3D
  // ==========================================================

  let best =
    null;

  let bestD2 =
    Infinity;

  for(
    const q
    of hover3DPoints
  ){

    const dx =
      q[0]-px;

    const dy =
      q[1]-py;

    const d2 =
      dx*dx
      + dy*dy;

    if(d2 < bestD2){

      bestD2 =
        d2;

      best =
        q;
    }
  }

  if(
    best
    && bestD2 < 30*30
  ){

    showCursorInfo(
      px,
      py,
      best[2],
      best[3]
    );

  }
  else{

    hideCursorInfo();

  }
}


canvas.addEventListener(
  "mousemove",
  updateHover
);

canvas.addEventListener(
  "mouseleave",
  hideCursorInfo
);


canvas.addEventListener("mousedown", e => {
  dragging = true;
  lastX = e.clientX;
  lastY = e.clientY;
});


window.addEventListener("mouseup", () => {
  dragging = false;
});


window.addEventListener("mousemove", e => {

  if(!dragging)
    return;

  yaw += (e.clientX-lastX)*0.008;
  pitch += (e.clientY-lastY)*0.008;

  pitch = Math.max(-1.35,Math.min(1.35,pitch));

  lastX = e.clientX;
  lastY = e.clientY;

  render();
});


canvas.addEventListener("wheel", e => {

  e.preventDefault();

  zoom *= e.deltaY < 0 ? 1.10 : 0.91;
  zoom = Math.max(0.45,Math.min(2.8,zoom));

  render();

},{passive:false});


function default3D(){
  yaw   = -0.75;
  pitch =  0.72;
  zoom  =  1.00;

  render();
}


canvas.addEventListener("dblclick",default3D);

$("#reset").onclick = () => {
  viewMode = "3d";
  default3D();
};

$("#top").onclick = () => {
  viewMode = "2d";
  render();
};

function showMeta(data){

  const m = data.meta;

  const rows = [
    ["Plik",m.file],
    ["Początek zapisu",m.obs_time],
    ["Trigger",m.trigger_time],
    [
      "Trigger od początku",
      m.trigger_offset_s == null
        ? "—"
        : Number(m.trigger_offset_s).toFixed(3)+" s"
    ],
    ["Długość IQ",Number(m.duration_s).toFixed(3)+" s"],
    ["Sample rate",Number(m.sample_rate).toFixed(1)+" S/s"],
    ["FFT",m.nfft],
    ["Overlap",(Number(m.overlap)*100).toFixed(3)+"%"],
    ["Rozdzielczość",Number(m.bin_hz).toFixed(2)+" Hz/bin"],
    ["Peak względny",Number(m.peak_rel_db).toFixed(1)+" dB"],
    ["Peak Doppler",Number(m.peak_freq_hz).toFixed(1)+" Hz"],
    ["Event ID",m.event_id || "—"],
    ["Stop",m.stop_reason || "—"]
  ];

  $("#meta").innerHTML = rows.map(row =>
    `<div class="kv">
      <div class="k">${escapeHtml(row[0])}</div>
      <div>${escapeHtml(row[1])}</div>
    </div>`
  ).join("");
}


async function loadEvents(){

  try{

    const r = await fetch("/api/events?limit=120");

    if(!r.ok)
      throw new Error(await r.text());

    const data = await r.json();

    const select = $("#event");

    select.innerHTML = "";

    for(const event of data.events){

      const option = document.createElement("option");

      option.value = event.file;

      option.textContent =
        `${event.obs_time || event.file}  •  ${event.event_id || ""}`;

      select.appendChild(option);
    }

    if(data.events.length){

      $("#status").textContent =
        `Detekcji na liście: ${data.events.length}`;

      await loadSpectrogram();
    }
    else{
      $("#status").textContent = "Brak plików NPZ.";
    }
  }
  catch(error){
    $("#status").innerHTML =
      `<span class="err">${escapeHtml(error)}</span>`;
  }
}


async function loadSpectrogram(){

  const file = $("#event").value;
  const span = $("#span").value;
  const fft  = $("#fft").value;

  if(!file)
    return;

  $("#status").textContent = "Liczenie spektrogramu…";

  try{

    const r = await fetch(
      `/api/spectrogram?file=${encodeURIComponent(file)}&span=${span}&fft=${fft}`
    );

    if(!r.ok)
      throw new Error(await r.text());

    S = await r.json();

    showMeta(S);

    $("#status").textContent =
      `Gotowe • ${S.z.length} × ${S.z[0].length} punktów`;

    render();
  }
  catch(error){
    $("#status").innerHTML =
      `<span class="err">${escapeHtml(error)}</span>`;
  }
}


$("#load").onclick = loadSpectrogram;
$("#event").onchange = loadSpectrogram;
$("#span").onchange = loadSpectrogram;
$("#fft").onchange = loadSpectrogram;

window.addEventListener("resize",resize);

loadEvents();

setTimeout(resize,50);

</script>

</body>
</html>
"""


def scalar(z,key,default=None):

    try:
        a = z[key]

        if np.asarray(a).shape == ():
            return np.asarray(a).item()

    except Exception:
        pass

    return default


def safe_file(name):

    base = Path(name).name

    if base != name or not base.endswith(".npz"):
        raise ValueError("Nieprawidłowa nazwa pliku")

    path = (ROOT/base).resolve()

    if path.parent != ROOT or not path.is_file():
        raise FileNotFoundError(base)

    return path


def time_delta(start,trigger):

    try:
        a = datetime.fromisoformat(str(start).replace(" ","T"))
        b = datetime.fromisoformat(str(trigger).replace(" ","T"))

        return (b-a).total_seconds()

    except Exception:
        return None


def list_events(limit=120):

    files = sorted(
        ROOT.glob("SMP_*.npz"),
        key=lambda p:p.stat().st_mtime,
        reverse=True
    )

    files = files[:max(1,min(limit,MAX_EVENTS))]

    result = []

    for path in files:

        try:

            with np.load(path,allow_pickle=False) as z:

                result.append({
                    "file":path.name,
                    "obs_time":str(scalar(z,"obs_time","")),
                    "trigger_time":str(scalar(z,"trigger_time","")),
                    "event_id":str(
                        scalar(z,"adaptive_event_id","")
                    ),
                    "tier":int(
                        scalar(z,"adaptive_tier",0) or 0
                    ),
                    "stop_reason":str(
                        scalar(z,"adaptive_stop_reason","")
                    ),
                    "size":path.stat().st_size
                })

        except Exception:
            continue

    return result


def make_spectrogram(path,span=300.0,fft_size=4096):

    with np.load(path,allow_pickle=False) as z:

        samples = np.asarray(
            z["samples"],
            dtype=np.complex64
        )

        sample_rate = float(
            scalar(z,"sample_rate",0.0)
        )

        centre_freq = float(
            scalar(z,"centre_freq",0.0)
        )

        obs_time = str(
            scalar(z,"obs_time","")
        )

        trigger_time = str(
            scalar(z,"trigger_time","")
        )

        event_id = str(
            scalar(z,"adaptive_event_id","")
        )

        stop_reason = str(
            scalar(z,"adaptive_stop_reason","")
        )

    if sample_rate <= 0:
        raise ValueError("Błędny sample_rate")

    allowed = {
        2048,
        4096,
        8192
    }

    if fft_size not in allowed:
        fft_size = 4096

    if samples.size < fft_size:
        raise ValueError(
            "Za mało próbek dla FFT"
        )

    # ---------------------------------------------------------
    # GRAVES w naszych NPZ znajduje się przy +2000 Hz baseband
    # ---------------------------------------------------------

    TARGET_BASEBAND_HZ = 2000.0

    NFFT = fft_size

    # Zostawiamy krok 128 próbek.
    # Dzięki temu zwiększenie FFT daje większą rozdzielczość
    # częstotliwościową bez utraty gęstości próbkowania osi czasu.
    HOP = 128

    OVERLAP = (
        1.0
        - HOP / NFFT
    )

    nframes = (
        1
        + (samples.size-NFFT)//HOP
    )

    if nframes <= 0:
        raise ValueError(
            "Brak klatek STFT"
        )

    # Maksymalnie 480 przekrojów czasu.
    # To nadal wielokrotnie więcej niż poprzednie 120.
    MAX_ROWS = 480

    frame_indexes = np.unique(
        np.linspace(
            0,
            nframes-1,
            min(
                nframes,
                MAX_ROWS
            )
        ).astype(int)
    )

    window = np.hanning(
        NFFT
    ).astype(np.float32)

    norm = max(
        float(window.sum()),
        1.0
    )

    baseband_freq = np.fft.fftshift(
        np.fft.fftfreq(
            NFFT,
            d=1.0/sample_rate
        )
    )

    doppler = (
        baseband_freq
        - TARGET_BASEBAND_HZ
    )

    requested_span = max(
        100.0,
        min(
            float(span),
            3000.0
        )
    )

    freq_indexes = np.flatnonzero(
        np.abs(doppler)
        <= requested_span
    )

    if freq_indexes.size < 3:
        raise ValueError(
            "Brak binów GRAVES"
        )

    doppler_selected = (
        doppler[freq_indexes]
    )

    rows = []
    times = []

    for fi in frame_indexes:

        begin = int(
            fi * HOP
        )

        segment = (
            samples[
                begin:begin+NFFT
            ]
            * window
        )

        spectrum = np.fft.fftshift(
            np.fft.fft(
                segment,
                n=NFFT
            )
        )

        db = (
            20.0
            * np.log10(
                np.maximum(
                    np.abs(spectrum)
                    / norm,
                    1e-12
                )
            )
        )

        rows.append(
            db[freq_indexes]
        )

        times.append(
            (
                begin
                + NFFT/2
            )
            / sample_rate
        )

    power = np.asarray(
        rows,
        dtype=np.float32
    )

    times = np.asarray(
        times,
        dtype=np.float64
    )

    trigger_offset = time_delta(
        obs_time,
        trigger_time
    )

    # ---------------------------------------------------------
    # PRE-trigger jako profil tła
    # ---------------------------------------------------------

    if (
        trigger_offset is not None
        and trigger_offset > 0.3
    ):

        pre = (
            times
            < max(
                0.0,
                trigger_offset-0.15
            )
        )

    else:

        pre = np.zeros(
            len(times),
            dtype=bool
        )

        pre[
            :max(
                3,
                len(times)//4
            )
        ] = True

    if np.count_nonzero(pre) >= 3:

        background = np.median(
            power[pre],
            axis=0
        )

    else:

        background = np.median(
            power,
            axis=0
        )

    relative = (
        power
        - background[
            None,
            :
        ]
    )

    # Zachowujemy słabe struktury.
    # Nie wycinamy już 1.5 dB jak w V2.
    display = np.maximum(
        relative,
        0.0
    )

    positive = display[
        display > 0
    ]

    if positive.size:

        ceiling = float(
            np.percentile(
                positive,
                99.6
            )
        )

    else:

        ceiling = 10.0

    ceiling = max(
        ceiling,
        6.0
    )

    peak_index = np.unravel_index(
        np.argmax(relative),
        relative.shape
    )

    peak_db = float(
        relative[
            peak_index
        ]
    )

    peak_freq = float(
        doppler_selected[
            peak_index[1]
        ]
    )

    return {

        "freq_hz":
            np.round(
                doppler_selected,
                3
            ).tolist(),

        "time_s":
            np.round(
                times,
                4
            ).tolist(),

        "z":
            np.round(
                display,
                2
            ).tolist(),

        "z_floor":
            0.0,

        "z_ceil":
            round(
                ceiling,
                2
            ),

        "meta":{

            "file":
                path.name,

            "obs_time":
                obs_time,

            "trigger_time":
                trigger_time,

            "trigger_offset_s":
                trigger_offset,

            "duration_s":
                samples.size
                / sample_rate,

            "sample_rate":
                sample_rate,

            "centre_freq":
                centre_freq,

            "target_baseband_hz":
                TARGET_BASEBAND_HZ,

            "nfft":
                NFFT,

            "overlap":
                OVERLAP,

            "hop":
                HOP,

            "bin_hz":
                sample_rate/NFFT,

            "peak_rel_db":
                peak_db,

            "peak_freq_hz":
                peak_freq,

            "event_id":
                event_id,

            "stop_reason":
                stop_reason
        }
    }


class Handler(BaseHTTPRequestHandler):

    def send_bytes(
        self,
        code,
        body,
        content_type
    ):

        self.send_response(code)

        self.send_header(
            "Content-Type",
            content_type
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)


    def do_GET(self):

        try:

            url = urllib.parse.urlparse(
                self.path
            )

            query = urllib.parse.parse_qs(
                url.query
            )

            if url.path == "/":

                return self.send_bytes(
                    200,
                    HTML.encode("utf-8"),
                    "text/html; charset=utf-8"
                )

            if url.path == "/healthz":

                return self.send_bytes(
                    200,
                    b'{"ok":true}',
                    "application/json"
                )

            if url.path == "/api/events":

                limit = int(
                    query.get(
                        "limit",
                        ["120"]
                    )[0]
                )

                body = json.dumps(
                    {
                        "events":
                            list_events(limit)
                    },
                    ensure_ascii=False
                ).encode("utf-8")

                return self.send_bytes(
                    200,
                    body,
                    "application/json; charset=utf-8"
                )

            if url.path == "/api/spectrogram":

                name = query.get(
                    "file",
                    [""]
                )[0]

                span = float(
                    query.get(
                        "span",
                        ["600"]
                    )[0]
                )

                fft_size = int(
                    query.get(
                        "fft",
                        ["4096"]
                    )[0]
                )

                data = make_spectrogram(
                    safe_file(name),
                    span,
                    fft_size
                )

                body = json.dumps(
                    data,
                    ensure_ascii=False,
                    separators=(",",":")
                ).encode("utf-8")

                return self.send_bytes(
                    200,
                    body,
                    "application/json; charset=utf-8"
                )

            return self.send_bytes(
                404,
                b"not found",
                "text/plain"
            )

        except Exception as error:

            body = json.dumps(
                {
                    "error":
                        str(error)
                },
                ensure_ascii=False
            ).encode("utf-8")

            return self.send_bytes(
                500,
                body,
                "application/json; charset=utf-8"
            )


    def log_message(
        self,
        fmt,
        *args
    ):

        print(
            "%s - %s" % (
                self.address_string(),
                fmt % args
            ),
            flush=True
        )


if __name__ == "__main__":

    print(
        f"MeteorRadio 3D: "
        f"http://{HOST}:{PORT}",
        flush=True
    )

    ThreadingHTTPServer(
        (HOST,PORT),
        Handler
    ).serve_forever()
