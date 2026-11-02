"""Dashboard web local para diskmon (solo biblioteca estándar).

Rutas:
    GET /                      Panel HTML
    GET /api/scan[?save=1]     Escaneo actual (cacheado unos segundos)
    GET /api/history?device=X  Histórico de un disco
    GET /api/devices           Discos con datos históricos
    GET /api/health            Estado del servicio
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from .collect import scan
from .config import Config
from .history import History


class ScanCache:
    """Cachea el último escaneo para no golpear los discos en cada refresco."""

    def __init__(self, ttl: int = 30):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._timestamp = 0.0
        self._data: Optional[dict[str, Any]] = None

    def get(self, config: Config, force: bool = False, save: bool = False) -> dict[str, Any]:
        with self._lock:
            fresh = self._data is not None and (time.time() - self._timestamp) < self.ttl
            if fresh and not force and not save:
                return self._data  # type: ignore[return-value]
            result = scan(config)
            if save:
                try:
                    History(config.db_file).save_scan(result)
                except (OSError, sqlite3.Error):
                    pass
            self._data = result.to_dict()
            self._timestamp = time.time()
            return self._data


PAGE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DiskMon · salud de discos</title>
<style>
  :root{
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2330; --border:#2d3644;
    --text:#e6edf3; --muted:#8b949e; --green:#3fb950; --yellow:#d29922;
    --red:#f85149; --blue:#58a6ff; --gray:#6e7681;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:15px}
  header{display:flex;align-items:center;gap:16px;flex-wrap:wrap;
         padding:20px 28px;border-bottom:1px solid var(--border);background:var(--panel)}
  header h1{margin:0;font-size:22px;letter-spacing:.5px}
  header h1 span{color:var(--blue)}
  #meta{color:var(--muted);font-size:13px}
  #summary{display:flex;gap:8px;margin-left:auto;flex-wrap:wrap}
  .chip{padding:4px 10px;border-radius:999px;background:var(--panel2);
        border:1px solid var(--border);font-size:12px;color:var(--muted)}
  .chip b{color:var(--text)}
  button{background:var(--panel2);color:var(--text);border:1px solid var(--border);
         border-radius:8px;padding:7px 14px;cursor:pointer;font-size:13px}
  button:hover{border-color:var(--blue)}
  main{padding:24px 28px;display:grid;gap:18px;
       grid-template-columns:repeat(auto-fill,minmax(430px,1fr))}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:14px;
        padding:18px 20px;position:relative;overflow:hidden}
  .card.critical{border-color:var(--red)}
  .card.warning{border-color:var(--yellow)}
  .card-top{display:flex;gap:16px;align-items:center}
  .ring{--pct:0;--col:var(--gray);width:78px;height:78px;border-radius:50%;flex:0 0 78px;
        background:conic-gradient(var(--col) calc(var(--pct)*1%), #262d3a 0);
        display:grid;place-items:center}
  .ring .inner{width:60px;height:60px;border-radius:50%;background:var(--panel);
        display:grid;place-items:center;font-weight:700;font-size:20px}
  .ring .inner small{font-size:10px;color:var(--muted);font-weight:400;display:block;
        text-align:center;margin-top:-2px}
  .title{min-width:0}
  .title h2{margin:0 0 2px;font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .title .sub{color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .verdict{font-weight:600;font-size:13px;margin-top:4px}
  .verdict.ok{color:var(--green)} .verdict.warning{color:var(--yellow)}
  .verdict.critical{color:var(--red)} .verdict.unknown{color:var(--gray)}
  .metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:16px}
  .metric{background:var(--panel2);border-radius:9px;padding:8px 10px}
  .metric .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
  .metric .v{font-size:14px;margin-top:2px}
  .issues{margin:14px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:6px}
  .issues li{font-size:13px;line-height:1.35;padding-left:10px;border-left:3px solid var(--border)}
  .issues li.critical{border-color:var(--red)} .issues li.warning{border-color:var(--yellow)}
  .issues li.info{border-color:var(--gray);color:var(--muted)}
  .parts{margin-top:12px;color:var(--muted);font-size:12px}
  .bar{height:5px;background:#262d3a;border-radius:4px;overflow:hidden;margin-top:4px}
  .bar i{display:block;height:100%;background:var(--blue)}
  .ok-text{color:var(--green);font-size:13px;margin-top:12px}
  section.history{margin:8px 28px 40px;background:var(--panel);border:1px solid var(--border);
        border-radius:14px;padding:18px 20px}
  section.history h2{margin:0 0 12px;font-size:16px}
  .hist-controls{display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
  select{background:var(--panel2);color:var(--text);border:1px solid var(--border);
         border-radius:8px;padding:6px 10px}
  canvas{width:100%;height:220px;display:block}
  #histtable{overflow-x:auto;margin-top:12px}
  table{border-collapse:collapse;width:100%;font-size:12px}
  th,td{padding:6px 8px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
  th{color:var(--muted);font-weight:500}
  td.num{text-align:right}
  .foot{color:var(--muted);font-size:12px;text-align:center;padding:0 0 28px}
  @media(max-width:560px){main{padding:16px}.card-top{flex-wrap:wrap}}
</style>
</head>
<body>
<header>
  <h1>Disk<span>Mon</span></h1>
  <div id="meta">cargando…</div>
  <div id="summary"></div>
  <button id="refresh">Actualizar</button>
</header>
<main id="cards"></main>
<section class="history">
  <h2>Evolución histórica</h2>
  <div class="hist-controls">
    <select id="device"></select>
    <span id="histinfo" style="color:var(--muted);font-size:12px"></span>
  </div>
  <canvas id="chart"></canvas>
  <div id="histtable"></div>
</section>
<div class="foot">DiskMon · datos SMART leídos localmente · se actualiza cada 60 s</div>
<script>
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '—').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtBytes = (n) => {
  if (n == null) return '—';
  const u = ['B','KB','MB','GB','TB','PB']; let v = n, i = 0;
  while (v >= 1000 && i < u.length - 1) { v /= 1000; i++; }
  return v.toFixed(i ? 1 : 0).replace('.', ',') + ' ' + u[i];
};
const fmtHours = (h) => h == null ? '—' : h.toLocaleString('es-ES') + ' h';
const colorFor = (a) => a === 'critical' ? 'var(--red)' : a === 'warning'
  ? 'var(--yellow)' : a === 'ok' ? 'var(--green)' : 'var(--gray)';
const labelFor = (a) => a === 'critical' ? 'CRÍTICO' : a === 'warning'
  ? 'AVISO' : a === 'ok' ? 'OK' : 'DESCONOCIDO';

let current = null;

function render(data) {
  current = data;
  $('#meta').textContent = 'Host ' + (data.hostname || '—') + ' · ' + (data.started_at || '');
  const s = data.summary || {};
  $('#summary').innerHTML =
    '<span class="chip"><b>' + (s.disks ?? 0) + '</b> discos</span>' +
    '<span class="chip" style="color:var(--green)"><b>' + (s.ok ?? 0) + '</b> sanos</span>' +
    '<span class="chip" style="color:var(--yellow)"><b>' + (s.warning ?? 0) + '</b> avisos</span>' +
    '<span class="chip" style="color:var(--red)"><b>' + (s.critical ?? 0) + '</b> críticos</span>';

  const cards = (data.disks || []).map((d) => {
    const score = d.score == null ? 0 : d.score;
    const issues = (d.issues || []).filter(i => i.severity !== 'info');
    const issueHtml = issues.length
      ? '<ul class="issues">' + issues.map(i =>
          '<li class="' + esc(i.severity) + '"><b>' + labelFor(i.severity) + '</b> ' +
          esc(i.message) + '</li>').join('') + '</ul>'
      : '<div class="ok-text">Sin incidencias detectadas.</div>';
    const parts = (d.partitions || []).map(p => {
      const label = p.mountpoint || p.name;
      const pct = p.use_percent == null ? '' :
        ' · ' + p.use_percent.toFixed(0) + '%' + (p.use_percent >= 90 ? ' ⚠' : '');
      return esc(label + ' (' + (p.fstype || '?') + ')' + pct);
    }).join('<br>');
    const m = d.metrics || {};
    const temp = m.temperature_c == null ? '—' : m.temperature_c.toFixed(0) + ' ºC';
    const wear = m.wear_percent == null ? '—' : m.wear_percent + '%';
    return '<article class="card ' + esc(d.alert_level) + '">' +
      '<div class="card-top">' +
        '<div class="ring" style="--pct:' + score + ';--col:' + colorFor(d.alert_level) + '">' +
          '<div class="inner">' + (d.score == null ? '?' : score) +
          '<small>/100</small></div></div>' +
        '<div class="title"><h2>' + esc(d.device) + ' · ' + esc(d.model || 'Desconocido') + '</h2>' +
          '<div class="sub">' + esc(d.kind) + ' · ' + fmtBytes(d.size_bytes) + ' · ' +
          esc((d.transport || 'bus ?').toUpperCase()) + ' · ' + esc(d.serial || 'sin serie') + '</div>' +
          '<div class="verdict ' + esc(d.alert_level) + '">' + esc(d.grade) + ' · ' +
          esc(d.verdict) + '</div></div>' +
      '</div>' +
      '<div class="metrics">' +
        '<div class="metric"><div class="k">Temperatura</div><div class="v">' + esc(temp) + '</div></div>' +
        '<div class="metric"><div class="k">Horas</div><div class="v">' + fmtHours(m.power_on_hours) + '</div></div>' +
        '<div class="metric"><div class="k">Desgaste</div><div class="v">' + esc(wear) + '</div></div>' +
        '<div class="metric"><div class="k">Reasignados</div><div class="v">' + esc(m.reallocated_sectors ?? '—') + '</div></div>' +
        '<div class="metric"><div class="k">Pendientes</div><div class="v">' + esc(m.pending_sectors ?? '—') + '</div></div>' +
        '<div class="metric"><div class="k">Errores log</div><div class="v">' + esc(m.error_log_count ?? '—') + '</div></div>' +
      '</div>' + issueHtml +
      (parts ? '<div class="parts">' + parts + '</div>' : '') +
    '</article>';
  });
  $('#cards').innerHTML = cards.join('') ||
    '<div class="card">No se han detectado discos analizables.</div>';

  const sel = $('#device');
  const prev = sel.value;
  const opts = (data.disks || []).map(d => d.device);
  sel.innerHTML = opts.map(v => '<option value="' + esc(v) + '">' + esc(v) + '</option>').join('');
  if (opts.includes(prev)) sel.value = prev;
  loadHistory();
}

async function refresh(save) {
  try {
    const r = await fetch('/api/scan' + (save ? '?save=1' : ''), {cache:'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    render(await r.json());
  } catch (e) {
    $('#meta').textContent = 'Error al escanear: ' + e.message;
  }
}

async function loadHistory() {
  const device = $('#device').value;
  if (!device) return;
  try {
    const r = await fetch('/api/history?device=' + encodeURIComponent(device) + '&limit=120');
    const data = await r.json();
    drawChart(data.rows || []);
    renderTable(data.rows || []);
    $('#histinfo').textContent = (data.rows || []).length + ' registros';
  } catch (e) { $('#histinfo').textContent = 'sin histórico'; }
}

function drawChart(rows) {
  const cv = $('#chart'), ctx = cv.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (rows.length < 2) {
    ctx.fillStyle = '#8b949e'; ctx.font = '13px system-ui';
    ctx.fillText('Aún no hay suficientes datos históricos (ejecuta diskmon scan).', 10, h/2);
    return;
  }
  const data = rows.slice().reverse().filter(r => r.score != null);
  if (data.length < 2) {
    ctx.fillStyle = '#8b949e'; ctx.font = '13px system-ui';
    ctx.fillText('Aún no hay suficientes datos históricos (ejecuta diskmon scan).', 10, h/2);
    return;
  }
  const padL = 34, padR = 10, padT = 12, padB = 22;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  ctx.strokeStyle = '#2d3644'; ctx.fillStyle = '#8b949e'; ctx.font = '11px system-ui';
  for (const v of [0, 25, 50, 75, 100]) {
    const y = padT + plotH * (1 - v / 100);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    ctx.fillText(String(v), 6, y + 4);
  }
  const x = i => padL + (data.length === 1 ? plotW/2 : plotW * i / (data.length - 1));
  const y = v => padT + plotH * (1 - v / 100);
  ctx.beginPath();
  data.forEach((r, i) => i ? ctx.lineTo(x(i), y(r.score)) : ctx.moveTo(x(i), y(r.score)));
  ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 2; ctx.stroke();
  ctx.lineTo(x(data.length - 1), padT + plotH); ctx.lineTo(x(0), padT + plotH);
  ctx.closePath(); ctx.fillStyle = 'rgba(88,166,255,.12)'; ctx.fill();
  data.forEach((r, i) => {
    const col = r.alert_level === 'critical' ? '#f85149'
      : r.alert_level === 'warning' ? '#d29922' : '#3fb950';
    ctx.beginPath(); ctx.arc(x(i), y(r.score), 2.5, 0, Math.PI * 2);
    ctx.fillStyle = col; ctx.fill();
  });
  ctx.fillStyle = '#8b949e';
  ctx.fillText(data[0].scanned_at.slice(0, 10), padL, h - 6);
  const last = data[data.length - 1].scanned_at.slice(0, 10);
  ctx.fillText(last, w - padR - ctx.measureText(last).width, h - 6);
}

function renderTable(rows) {
  if (!rows.length) { $('#histtable').innerHTML = ''; return; }
  const body = rows.slice(0, 25).map(r =>
    '<tr><td>' + esc(r.scanned_at) + '</td><td>' + esc(r.device) + '</td>' +
    '<td class="num">' + esc(r.score ?? '—') + '</td><td>' + esc(r.grade) + '</td>' +
    '<td>' + esc(r.verdict) + '</td>' +
    '<td class="num">' + (r.temperature_c == null ? '—' : r.temperature_c.toFixed(0) + ' ºC') + '</td>' +
    '<td class="num">' + esc(r.power_on_hours ?? '—') + '</td>' +
    '<td class="num">' + esc(r.wear_percent ?? '—') + '</td></tr>').join('');
  $('#histtable').innerHTML = '<table><thead><tr><th>Fecha</th><th>Disco</th>' +
    '<th>Puntos</th><th>Nota</th><th>Estado</th><th>Temp</th><th>Horas</th>' +
    '<th>Desgaste %</th></tr></thead><tbody>' + body + '</tbody></table>';
}

$('#refresh').addEventListener('click', () => refresh(true));
$('#device').addEventListener('change', loadHistory);
window.addEventListener('resize', () => current && loadHistory());
refresh(false);
setInterval(() => refresh(false), 60000);
</script>
</body>
</html>
"""


def make_handler(config: Config, cache: ScanCache) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "DiskMon/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:  # silencio por defecto
            return

        def _send(self, body: bytes, status: int = 200, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, status: int = 200) -> None:
            self._send(json.dumps(data, ensure_ascii=False).encode("utf-8"), status)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            try:
                if parsed.path in ("/", "/index.html"):
                    self._send(PAGE.encode("utf-8"), content_type="text/html")
                elif parsed.path == "/api/scan":
                    force = params.get("force", ["0"])[0] in ("1", "true")
                    save = params.get("save", ["0"])[0] in ("1", "true")
                    self._json(cache.get(config, force=force, save=save))
                elif parsed.path == "/api/history":
                    device = params.get("device", [None])[0]
                    limit = int(params.get("limit", ["100"])[0])
                    rows = History(config.db_file).query(device=device, limit=limit)
                    self._json({"device": device, "rows": rows})
                elif parsed.path == "/api/devices":
                    self._json({"devices": History(config.db_file).devices()})
                elif parsed.path == "/api/health":
                    age = (
                        round(time.time() - cache._timestamp, 1)
                        if cache._timestamp
                        else None
                    )
                    self._json(
                        {
                            "status": "ok",
                            "db": History(config.db_file).stats(),
                            "cache_age_seconds": age,
                        }
                    )
                else:
                    self._json({"error": "ruta no encontrada"}, HTTPStatus.NOT_FOUND)
            except (ValueError, OSError, sqlite3.Error) as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    return Handler


def serve(config: Config, host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Arranca el dashboard hasta Ctrl-C."""
    host = host or config.web_host
    port = port or config.web_port
    cache = ScanCache(ttl=config.web_cache_seconds)
    httpd = ThreadingHTTPServer((host, port), make_handler(config, cache))
    print(f"DiskMon dashboard en http://{host}:{port}  (Ctrl-C para salir)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando dashboard.")
    finally:
        httpd.server_close()
