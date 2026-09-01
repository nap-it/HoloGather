"""Map / GPS / heading visualization subscriber.

Mirrors the RGB camera subscriber's methodology — a `BaseSubscriberProcess`
that consumes Zenoh streams and serves a live web view — but for location data:
it subscribes to the VAM GPS, phone GPS and heading topics and serves a Leaflet
map with the position marker + heading arrow. RGB is intentionally NOT handled
here (served separately by the RGB subscriber); open this map alongside it to
compare position/heading against the camera.

Serves:
    GET /        -> the map page (Leaflet + marker + heading arrow)
    GET /state   -> latest GPS/heading JSON (polled by the page)

Optional: set `gpsd_host` in the [MAP] config section to overlay the raw gpsd
receiver position (green) for live ground-truth comparison.
"""

from __future__ import annotations

import configparser
import json
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import msgpack  # type: ignore

from src.handlers.base_subscriber import BaseSubscriberProcess
from src.serialization.packet_codec import decode
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO
from src.zenoh_utils.sensor_zenoh_reader import SensorPacket, SensorZenohReader


class MapSubscriber(BaseSubscriberProcess):
    """Subscribes to GPS (VAM/phone) + heading and serves a live map page."""

    def __init__(self, config_file: str):
        super().__init__("MapSubscriber")
        self.config_file = config_file
        cfg = configparser.ConfigParser()
        cfg.read(config_file)

        S = "MAP"
        self.web_port = cfg.getint(S, "web_port", fallback=8797) if cfg.has_section(S) else 8797
        qsz = cfg.getint(S, "sensor_queue_size", fallback=25) if cfg.has_section(S) else 25
        self.gpsd_host = (cfg.get(S, "gpsd_host", fallback="").strip() or None) if cfg.has_section(S) else None
        self.gpsd_port = cfg.getint(S, "gpsd_port", fallback=2947) if cfg.has_section(S) else 2947

        def topic(section, fb):
            return cfg.get(section, "topic", fallback=fb) if cfg.has_section(section) else fb
        self.t_vam = topic("VAM_LOCATION", "Hololens/VamLocation")
        self.t_phone = topic("PHONE_LOCATION", "Hololens/PhoneLocation")
        self.t_hdg = topic("HEADING", "Hololens/Heading")

        # One SensorZenohReader per topic (project's building block), each draining
        # into its own overwritable FIFO.
        self._readers = {
            "vam": (OverWritableMPFIFO[SensorPacket](max_size=qsz), None),
            "phone": (OverWritableMPFIFO[SensorPacket](max_size=qsz), None),
            "hdg": (OverWritableMPFIFO[SensorPacket](max_size=qsz), None),
        }
        self._readers["vam"] = (self._readers["vam"][0], SensorZenohReader(self.t_vam, self._readers["vam"][0]))
        self._readers["phone"] = (self._readers["phone"][0], SensorZenohReader(self.t_phone, self._readers["phone"][0]))
        self._readers["hdg"] = (self._readers["hdg"][0], SensorZenohReader(self.t_hdg, self._readers["hdg"][0]))

        # Latest-state shared with the HTTP server thread (same process → Lock).
        self._lock = threading.Lock()
        self._state = {"vam": None, "phone": None, "heading": None, "gpsd": None}
        self._httpd = None
        self._gpsd_thread = None
        self._gpsd_stop = threading.Event()

    # ── state helpers ─────────────────────────────────────────────────────────
    def _set(self, key, value):
        value["t"] = time.time()
        with self._lock:
            self._state[key] = value

    def _snapshot(self):
        now = time.time()
        with self._lock:
            s = {k: (dict(v) if v else None) for k, v in self._state.items()}
        age = {}
        for k, v in s.items():
            age[k] = round(now - v["t"], 2) if v else None
        s["age"] = age
        return s

    # ── decode one packet into a lat/lon or heading value ─────────────────────
    def _drain(self, key):
        buf, _reader = self._readers[key]
        if buf.is_empty():
            return
        packet = buf.get()
        if packet is None:
            return
        self._emit_packet_airtime_ms(packet)
        try:
            _meta, payload = decode(packet.message)
            data = msgpack.unpackb(payload, raw=False)
        except Exception as exc:
            self.logger.debug("map decode error (%s): %s", key, exc)
            return
        if key == "hdg":
            h = data.get("heading")
            if h is not None:
                self._set("heading", {"deg": float(h)})
        else:
            lat, lon = data.get("latitude"), data.get("longitude")
            if lat is not None and lon is not None and abs(lat) < 1e6 and abs(lon) < 1e6:
                self._set(key, {"lat": float(lat), "lon": float(lon)})

    # ── optional gpsd raw-receiver ground truth ───────────────────────────────
    def _gpsd_loop(self):
        while not self._gpsd_stop.is_set():
            try:
                with socket.create_connection((self.gpsd_host, self.gpsd_port), timeout=5) as sock:
                    sock.sendall(b'?WATCH={"enable":true,"json":true};\n')
                    sock.settimeout(1.0)
                    buf = b""
                    self.logger.info("gpsd ground truth connected: %s:%d", self.gpsd_host, self.gpsd_port)
                    while not self._gpsd_stop.is_set():
                        try:
                            chunk = sock.recv(4096)
                        except socket.timeout:
                            continue
                        if not chunk:
                            break
                        buf += chunk
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            self._gpsd_line(line)
            except Exception as exc:
                if not self._gpsd_stop.is_set():
                    self.logger.warning("gpsd connect failed (%s); retry in 3s", exc)
                    self._gpsd_stop.wait(3.0)

    def _gpsd_line(self, line: bytes):
        line = line.strip()
        if b'"TPV"' not in line:
            return
        try:
            d = json.loads(line)
        except Exception:
            return
        if d.get("class") != "TPV" or d.get("mode", 0) < 2:
            return
        lat, lon = d.get("lat"), d.get("lon")
        if lat is not None and lon is not None:
            self._set("gpsd", {"lat": float(lat), "lon": float(lon)})

    # ── HTTP server ───────────────────────────────────────────────────────────
    def _start_http(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass  # silence per-request logging

            def do_GET(self):
                if self.path == "/" or self.path.startswith("/index"):
                    body = _PAGE.encode()
                    ctype = "text/html; charset=utf-8"
                elif self.path == "/state":
                    body = json.dumps(outer._snapshot()).encode()
                    ctype = "application/json"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.web_port), H)
        threading.Thread(target=self._httpd.serve_forever, daemon=True,
                         name="map-http").start()

    # ── BaseSubscriberProcess lifecycle ───────────────────────────────────────
    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        for key, (_buf, reader) in self._readers.items():
            reader.run()
            self.logger.info("Map subscribed: %s", getattr(reader, "key_expr", key))
        if self.gpsd_host:
            self._gpsd_thread = threading.Thread(target=self._gpsd_loop, daemon=True, name="map-gpsd")
            self._gpsd_thread.start()
        self._start_http()
        self.logger.info("Map view → http://localhost:%d/", self.web_port)

        while not self._stop_event.is_set():
            self._flush_rolling_metrics()
            for key in ("vam", "phone", "hdg"):
                self._drain(key)
            time.sleep(0.005)

    def _request_stop(self):
        self.logger.info("Requesting map subscriber stop...")
        self._stop_event.set()
        for _buf, _reader in self._readers.values():
            _buf.put(None)

    def _subscriber_cleanup(self):
        self.logger.info("Cleaning up map subscriber...")
        self._gpsd_stop.set()
        for _buf, reader in self._readers.values():
            try:
                reader.stop()
            except Exception as exc:
                self.logger.debug("Error stopping reader: %s", exc)
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
        self.logger.info("Cleanup complete.")


_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Live GPS / Heading map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 html,body{margin:0;height:100%;font-family:system-ui,sans-serif;background:#0b0d10;color:#e5e7eb}
 #map{height:calc(100vh - 46px)}
 .bar{display:flex;gap:14px;flex-wrap:wrap;align-items:center;height:46px;padding:0 14px;font-size:13px;box-sizing:border-box}
 .k{color:#9ca3af}.v{font-weight:600}.stale{color:#f87171}.ok{color:#34d399}
 button{background:#1f2937;color:#e5e7eb;border:1px solid #374151;border-radius:6px;padding:3px 9px;cursor:pointer;font-size:12px}
 button.active{background:#2563eb;border-color:#2563eb}
</style></head><body>
<div class="bar">
 <span class="k">GPS:</span>
 <button id="src-vam" class="active" onclick="setSrc('vam')">VAM</button>
 <button id="src-phone" onclick="setSrc('phone')">Phone</button>
 <span class="k">Heading offset</span>
 <input type="range" id="hoff" min="-180" max="180" value="0" oninput="ho()"><span class="v" id="hoffv">0°</span>
 <span><span class="k">lat,lon</span> <span class="v" id="ll">—</span></span>
 <span><span class="k">hdg</span> <span class="v" id="hd">—</span></span>
 <span><span class="k">sel↔gpsd</span> <span class="v" id="gd">—</span></span>
 <span><span class="k">age gps</span> <span class="v" id="ag">—</span></span>
 <span><span class="k">age hdg</span> <span class="v" id="ah">—</span></span>
</div>
<div id="map"></div>
<script>
let src='vam',hoff=0,map,marker,trail,pts=[],gtMarker;
function distM(a1,o1,a2,o2){const R=6371000,dA=(a2-a1)*Math.PI/180,dO=(o2-o1)*Math.PI/180;
 const x=Math.sin(dA/2)**2+Math.cos(a1*Math.PI/180)*Math.cos(a2*Math.PI/180)*Math.sin(dO/2)**2;
 return R*2*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));}
function setSrc(s){src=s;document.getElementById('src-vam').classList.toggle('active',s==='vam');
 document.getElementById('src-phone').classList.toggle('active',s==='phone');pts=[];if(trail)trail.setLatLngs([]);}
function ho(){hoff=+document.getElementById('hoff').value;document.getElementById('hoffv').textContent=hoff+'°';}
function icon(deg){return L.divIcon({className:'',iconAnchor:[22,22],
 html:`<svg viewBox="-14 -14 28 28" width="44" height="44" style="transform:rotate(${deg}deg)">
  <polygon points="0,-11 7,9 0,5 -7,9" fill="#2563eb" stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>`});}
function fmtAge(a){return a==null?'<span class="stale">none</span>':`<span class="${a<2?'ok':'stale'}">${a.toFixed(1)}s</span>`;}
// Start at a neutral world view; recenter on the first received position.
map=L.map('map').setView([0,0],2);
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',{maxZoom:20}).addTo(map);
trail=L.polyline([],{color:'#2563eb',weight:2,opacity:.6}).addTo(map);
let centered=false;
async function tick(){
 try{
  const s=await (await fetch('/state')).json();
  const g=s[src];
  document.getElementById('ll').textContent=g?`${g.lat.toFixed(6)}, ${g.lon.toFixed(6)}`:'—';
  const deg=s.heading?((s.heading.deg+hoff)%360+360)%360:null;
  document.getElementById('hd').textContent=deg!=null?`${Math.round(deg)}°`:'—';
  document.getElementById('ag').innerHTML=fmtAge(s.age[src]);
  document.getElementById('ah').innerHTML=fmtAge(s.age.heading);
  if(g){const ll=[g.lat,g.lon];
   if(!marker){marker=L.marker(ll,{icon:icon(deg||0)}).addTo(map);}
   else{marker.setLatLng(ll);marker.setIcon(icon(deg||0));}
   if(!centered){map.setView(ll,18);centered=true;}
   pts.push(ll);if(pts.length>400)pts.shift();trail.setLatLngs(pts);}
  const gt=s.gpsd;
  if(gt){if(!gtMarker){gtMarker=L.circleMarker([gt.lat,gt.lon],
    {radius:8,color:'#059669',weight:3,fillColor:'#10b981',fillOpacity:.5}).addTo(map).bindTooltip('gpsd (raw receiver)');}
   else gtMarker.setLatLng([gt.lat,gt.lon]);
   document.getElementById('gd').textContent=g?distM(g.lat,g.lon,gt.lat,gt.lon).toFixed(1)+' m':'—';}
  else document.getElementById('gd').textContent='—';
 }catch(e){}
}
setInterval(tick,200);
</script></body></html>"""
