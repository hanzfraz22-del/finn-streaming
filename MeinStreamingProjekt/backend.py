import sys
import os
import re
import queue
import concurrent.futures
import json
import urllib.parse
from flask import Flask, request, jsonify, render_template, send_from_directory, Response, stream_with_context

# Stelle sicher, dass das src/ Verzeichnis immer im Suchpfad ist
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSSIBLE_SRCS = [
    os.path.abspath(os.path.join(BASE_DIR, '..', 'src')),
    os.path.abspath(os.path.join(os.getcwd(), 'src')),
    os.path.abspath(os.path.join(BASE_DIR, 'src')),
]
for p in POSSIBLE_SRCS:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    from mediaforge.providers import resolve_provider
    from mediaforge.search import megakino_search, query_s_to
    from mediaforge.search import query as aniworld_search
except ImportError as e:
    print(f"[*] Hinweis: Direkter Import wird versucht ({e})...")
    try:
        import mediaforge
        from mediaforge.providers import resolve_provider
        from mediaforge.search import megakino_search, query_s_to
        from mediaforge.search import query as aniworld_search
    except Exception as e2:
        print(f"[!] Warnung: Scraper-Module nicht geladen: {e2}")

def ensure_database():
    try:
        from mediaforge.web.db import (
            init_db, init_app_settings_db, init_tmdb_cache_db, 
            init_provider_cache_db, init_browse_cache_db, 
            init_media_ignored_db, init_custom_paths_db
        )
        init_db()
        init_app_settings_db()
        init_provider_cache_db()
        init_tmdb_cache_db()
        init_browse_cache_db()
        init_media_ignored_db()
        init_custom_paths_db()
        print("[+] MediaForge Datenbank & Tabellen erfolgreich initialisiert.")
    except Exception as e:
        print(f"[*] DB Init Info: {e}")

ensure_database()

import threading
def _warmup_scraper_gate():
    try:
        print("[*] Waerme Scraper-Sitzung im Hintergrund auf...")
        megakino_search("a")
        print("[+] Scraper-Sitzung aufgewaermt (Highspeed aktiv)!")
    except Exception as e:
        print(f"[*] Warmup Hinweis: {e}")
threading.Thread(target=_warmup_scraper_gate, daemon=True).start()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=BASE_DIR)
app.config['TEMPLATES_AUTO_RELOAD'] = True

def slugify(text):
    if not text: return ""
    text = text.lower()
    text = re.sub(r'[^a-z0-9äöüß]+', '-', text)
    text = text.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
    return text.strip('-')

@app.route('/')
def index():
    return render_template('index.html')

@app.after_request
def add_cache_control_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/health')
@app.route('/api/ping')
def health_ping():
    return jsonify({'status': 'ok', 'server': 'Finn Streaming', 'alive': True}), 200

@app.route('/api/diag')
def api_diag():
    results = {}
    import time
    
    # Test 1: Megakino
    t0 = time.time()
    try:
        from mediaforge.search import megakino_search
        m = megakino_search("Inception")
        results["megakino"] = {"status": "ok", "count": len(m) if m else 0, "time": f"{time.time()-t0:.2f}s"}
    except Exception as e:
        results["megakino"] = {"status": "error", "error": str(e), "time": f"{time.time()-t0:.2f}s"}

    # Test 2: SerienStream suggest
    t0 = time.time()
    try:
        from mediaforge.search import query_s_to
        s = query_s_to("Breaking Bad")
        results["s_to_search"] = {"status": "ok", "count": len(s) if s else 0, "time": f"{time.time()-t0:.2f}s"}
    except Exception as e:
        results["s_to_search"] = {"status": "error", "error": str(e), "time": f"{time.time()-t0:.2f}s"}

    # Test 3: AniWorld search
    t0 = time.time()
    try:
        from mediaforge.search import query as aniworld_search
        a = aniworld_search("Naruto")
        results["aniworld_search"] = {"status": "ok", "count": len(a) if a else 0, "time": f"{time.time()-t0:.2f}s"}
    except Exception as e:
        results["aniworld_search"] = {"status": "error", "error": str(e), "time": f"{time.time()-t0:.2f}s"}

    # Test 4: FilmPalast
    t0 = time.time()
    try:
        from curl_cffi import requests as curl_requests
        r = curl_requests.get("https://filmpalast.to/stream/inception", impersonate="chrome120", timeout=5)
        results["filmpalast"] = {"status": "ok", "code": r.status_code, "time": f"{time.time()-t0:.2f}s"}
    except Exception as e:
        results["filmpalast"] = {"status": "error", "error": str(e), "time": f"{time.time()-t0:.2f}s"}

    # Test 5: VOE Direct
    t0 = time.time()
    try:
        from mediaforge.extractors.provider.voe import get_direct_link_from_voe
        v = get_direct_link_from_voe("https://voe.sx/e/tttij3lj1xlc")
        results["voe_direct"] = {"status": "ok", "url": v[:40] if v else None, "time": f"{time.time()-t0:.2f}s"}
    except Exception as e:
        import traceback
        results["voe_direct"] = {"status": "error", "error": str(e), "trace": traceback.format_exc(), "time": f"{time.time()-t0:.2f}s"}

    return jsonify(results)

@app.route('/manifest.json')
def manifest():
    manifest_data = {
        "name": "Finn Streaming",
        "short_name": "FinnStream",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#000000",
        "theme_color": "#E50914",
        "icons": [{"src": "https://upload.wikimedia.org/wikipedia/commons/0/08/Netflix_2015_logo.svg", "sizes": "192x192", "type": "image/svg+xml"}]
    }
    return jsonify(manifest_data)

@app.route('/sw.js')
def service_worker():
    return send_from_directory(BASE_DIR, 'sw.js', mimetype='application/javascript')

@app.route('/api/hls_proxy')
def hls_proxy():
    """HLS Reverse-Proxy: Schreibt M3U8 Playlists um und leitet Segmente live weiter,
    damit der IP-gebundene VOE Token immer von Render abgerufen wird."""
    target_url = request.args.get('url')
    if not target_url:
        return "Missing URL", 400

    import requests
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://megankiddifference.com/'
    }
    range_header = request.headers.get('Range')
    if range_header:
        headers['Range'] = range_header

    is_m3u8 = '.m3u8' in target_url or 'urlset' in target_url

    if is_m3u8:
        try:
            r = requests.get(target_url, headers=headers, timeout=12)
            if r.status_code != 200:
                return f"Fehler von Upstream: {r.status_code}", r.status_code

            content = r.text
            lines = content.splitlines()
            rewritten_lines = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    rewritten_lines.append('')
                elif stripped.startswith('#'):
                    if 'URI="' in stripped:
                        def replace_uri(m):
                            u = m.group(1)
                            full_u = urllib.parse.urljoin(target_url, u)
                            return f'URI="/api/hls_proxy?url={urllib.parse.quote(full_u)}"'
                        stripped = re.sub(r'URI="([^"]+)"', replace_uri, stripped)
                    rewritten_lines.append(stripped)
                else:
                    resolved = urllib.parse.urljoin(target_url, stripped)
                    rewritten_lines.append(f"/api/hls_proxy?url={urllib.parse.quote(resolved)}")

            rewritten_content = "\n".join(rewritten_lines)
            resp = app.make_response(rewritten_content)
            resp.headers['Content-Type'] = 'application/vnd.apple.mpegurl'
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            return resp
        except Exception as e:
            return f"Fehler beim Laden der Playlist: {e}", 502
    else:
        try:
            upstream = requests.get(target_url, headers=headers, stream=True, timeout=15)
            def generate():
                for chunk in upstream.iter_content(chunk_size=65536):
                    if chunk:
                        yield chunk

            resp = Response(
                stream_with_context(generate()),
                status=upstream.status_code,
                content_type=upstream.headers.get('content-type') or ('video/MP2T' if '.ts' in target_url else 'application/octet-stream')
            )
            resp.headers['Access-Control-Allow-Origin'] = '*'
            if 'Content-Range' in upstream.headers:
                resp.headers['Content-Range'] = upstream.headers['Content-Range']
            if 'Content-Length' in upstream.headers:
                resp.headers['Content-Length'] = upstream.headers['Content-Length']
            resp.headers['Cache-Control'] = 'public, max-age=86400'
            return resp
        except Exception as e:
            return f"Fehler beim Streamen des Segments: {e}", 502

@app.route('/api/voe_clean/<video_id>')
def voe_clean(video_id):
    """Proxy fuer sauberen, werbefreien VOE-Player ohne Popups und ohne Drittanbieter-Ad-Banner"""
    try:
        from curl_cffi import requests as curl_requests
        target_url = f"https://megankiddifference.com/e/{video_id}"
        resp = None
        for candidate in [target_url, f"https://voe.sx/e/{video_id}"]:
            try:
                r = curl_requests.get(
                    candidate,
                    impersonate="chrome120",
                    timeout=8,
                    headers={"Referer": "https://voe.sx/"},
                    allow_redirects=True
                )
                if r.status_code == 200 and len(r.text) > 2000:
                    resp = r
                    break
            except Exception:
                pass
        
        if not resp:
            return "Video-Stream konnte nicht geladen werden.", 404

        html = resp.text

        # 1. Base Tag fuer alle internen Player-Assets und Fonts
        base_tag = '<base href="https://megankiddifference.com/">\n'
        html = html.replace('<head>', '<head>\n' + base_tag)

        # 2. Skripte zur Blockierung von Popups und Werbebannern + JWPlayer HLS-Proxy Weiterleitung
        blocker = '''
        <script>
            // Popup-Fenster und Weiterleitungen komplett unterbinden
            window.open = function() { console.log("Blocked ad popup"); return null; };
            window.alert = function() {};
            window.confirm = function() { return true; };
            window.addEventListener('DOMContentLoaded', function() {
                if (typeof window.f98a024e !== 'undefined') {
                    window.f98a024e = { add: function(){}, config: function(){ return this; }, ignoreTo: function(){ return this; } };
                }
            });
            // JWPlayer Setup abfangen und Stream durch /api/hls_proxy leiten (verhindert 232011 / IP-Lock Fehler)
            (function() {
                function patchJw() {
                    if (typeof window.jwplayer !== 'undefined') {
                        var _origJw = window.jwplayer;
                        window.jwplayer = function(id) {
                            var inst = _origJw(id);
                            var _origSetup = inst.setup;
                            inst.setup = function(config) {
                                if (config) {
                                    if (config.source) {
                                        config.source = '/api/hls_proxy?url=' + encodeURIComponent(config.source);
                                    }
                                    if (config.fallback && Array.isArray(config.fallback)) {
                                        config.fallback.forEach(function(f) {
                                            if (f.file) f.file = '/api/hls_proxy?url=' + encodeURIComponent(f.file);
                                        });
                                    }
                                }
                                return _origSetup.call(inst, config);
                            };
                            return inst;
                        };
                        for (var k in _origJw) { window.jwplayer[k] = _origJw[k]; }
                    } else {
                        setTimeout(patchJw, 25);
                    }
                }
                patchJw();
            })();
        </script>
        <style>
            /* Alle Ad-Overlays, Banner und Phruk-Widgets unsichtbar und inaktiv machen */
            iframe[src*="phruk"], iframe[src*="traffic"], iframe[src*="ad"],
            div[class*="ad-"], div[id*="ad-"], div[class*="banner"], div[id*="banner"],
            .modal-backdrop, .guestMode, div[style*="z-index: 9999"], div[style*="z-index:9999"],
            div[style*="z-index: 1000"], div[style*="z-index:1000"] {
                display: none !important;
                visibility: hidden !important;
                pointer-events: none !important;
            }
        </style>
        '''
        html = html.replace('</head>', blocker + '\n</head>')

        # 3. Phruk.org, Twitter Ads & Evasive Ad-Skripte vollstaendig entfernen
        html = re.sub(r'<script[^>]*src=["\'][^"\']*(?:phruk\.org|ads-twitter\.com|evasivewashoutsociety|traffic)[^"\']*["\'][^>]*></script>', '', html)

        # 4. Popunder Registrierung entfernen
        html = re.sub(r'f98a024e\.add\(.*?\);', '', html)
        html = re.sub(r'var u7 = .*?return function.*?\}\)\(\);', 'var u7 = function() { return ""; };', html, flags=re.DOTALL)

        # 5. Anti-Sandbox / Debugger entfernen
        html = re.sub(r'c74a68dfbd15fcd6f23a6b26879bc82e\(\);', '', html)
        html = re.sub(r'debugger;', '', html)

        response = app.make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response
    except Exception as e:
        return f"Fehler beim Laden des Streams: {e}", 500

import concurrent.futures

def try_url(url, title):
    try:
        print(f"[*] Versuche URL: {url}")
        provider = resolve_provider(url)
        if not provider or not provider.episode_cls: return None
        
        # Teste zunaechst VOE mit Deutsch (schnellster Pfad)
        for lang in ["German", "Deutsch", "English"]:
            try:
                ep = provider.episode_cls(url=url, selected_language=lang, selected_provider="VOE")
                p_url = getattr(ep, 'provider_url', None)
                stream = None
                try:
                    stream = ep.stream_url
                except Exception:
                    pass
                if stream:
                    proxied_stream = f"/api/hls_proxy?url={urllib.parse.quote(stream)}" if ('.m3u8' in stream or 'urlset' in stream) else stream
                    embed_voe = None
                    if p_url:
                        clean = p_url.split('?')[0].rstrip('/')
                        vid_id = clean.split('/')[-1]
                        if len(vid_id) >= 6:
                            embed_voe = f"/api/voe_clean/{vid_id}"
                        else:
                            embed_voe = p_url
                    return {
                        "original_url": url,
                        "stream_url": proxied_stream,
                        "raw_stream_url": stream,
                        "embed_url": embed_voe,
                        "serie": title,
                        "provider": "VOE",
                        "language": lang,
                        "mode": "direct"
                    }
            except Exception:
                pass

        # Fallback auf alternative Hoster wie Vidoza oder Streamtape
        for p_name in ["Vidoza", "Streamtape", "Doodstream"]:
            for lang in ["German", "Deutsch", "English"]:
                try:
                    ep = provider.episode_cls(url=url, selected_language=lang, selected_provider=p_name)
                    p_url = getattr(ep, 'provider_url', None)
                    stream = None
                    try:
                        stream = ep.stream_url
                    except Exception:
                        pass
                    if stream:
                        proxied_stream = f"/api/hls_proxy?url={urllib.parse.quote(stream)}" if ('.m3u8' in stream or 'urlset' in stream) else stream
                        return {
                            "original_url": url,
                            "stream_url": proxied_stream,
                            "raw_stream_url": stream,
                            "embed_url": p_url,
                            "serie": title,
                            "provider": p_name,
                            "language": lang,
                            "mode": "direct"
                        }
                except Exception:
                    pass
    except Exception as e:
        print(f"[*] try_url fehler fuer {url}: {e}")
    return None

import queue

@app.route('/api/smart_play')
def smart_play():
    title = request.args.get('title', '')
    original_title = request.args.get('original_title', '')
    media_type = request.args.get('type', 'movie')
    season = request.args.get('season', '1')
    episode = request.args.get('episode', '1')
    tmdb_id = request.args.get('tmdb_id', '')

    if not title: return jsonify({"error": "Kein Titel übergeben"}), 400

    q = queue.Queue()
    
    # Intelligente Varianten generieren
    raw_titles = [title, original_title]
    for t in list(raw_titles):
        if not t: continue
        if ':' in t:
            raw_titles.append(t.split(':')[0].strip())
            raw_titles.append(t.replace(':', ' ').strip())
        if '-' in t:
            raw_titles.append(t.split('-')[0].strip())
            raw_titles.append(t.replace('-', ' ').strip())
        for art in ['The ', 'Der ', 'Die ', 'Das ', 'A ', 'Ein ', 'Eine ']:
            if t.lower().startswith(art.lower()):
                raw_titles.append(t[len(art):].strip())

    slugs = list(set([slugify(t) for t in raw_titles if t and slugify(t)]))
    urls_to_try = []
    for slug in slugs:
        if media_type == 'tv':
            urls_to_try.append(f"https://s.to/serie/{slug}/staffel-{season}/episode-{episode}")
            urls_to_try.append(f"https://aniworld.to/anime/stream/{slug}/staffel-{season}/episode-{episode}")
        else:
            urls_to_try.append(f"https://filmpalast.to/stream/{slug}")
            urls_to_try.append(f"https://filmpalast.to/stream/{slug}-1")

    # Schneller, nicht-blockierender ThreadPool
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
    try:
        def check_url_and_push(url):
            try:
                res = try_url(url, title)
                if res: q.put(res)
            except: pass
            
        for u in urls_to_try[:6]: 
            executor.submit(check_url_and_push, u)
            
        def api_search_worker(func, q_str, prefix, suffix, expected_type=None):
            if not q_str: return
            try:
                res = func(q_str)
                if res:
                    q_low = q_str.lower().strip()
                    def score(r):
                        t_low = r.get('title', '').lower()
                        pts = 0
                        if expected_type == 'movie' and r.get('is_series', False):
                            pts += 20
                        elif expected_type == 'tv':
                            if not r.get('is_series', True):
                                pts += 20
                            s_marker = f"staffel {season}"
                            if s_marker in t_low or f"s{season}" in t_low:
                                pts -= 50
                            elif "staffel" in t_low:
                                pts += 40
                        if t_low == q_low:
                            pts += 0
                        elif q_low in t_low:
                            pts += 1
                        else:
                            pts += 5
                        return pts
                    sorted_res = sorted(res, key=score)
                    for r in sorted_res[:4]:
                        if 'link' in r: executor.submit(check_url_and_push, f"{prefix}{r['link']}{suffix}")
                        elif 'url' in r: executor.submit(check_url_and_push, f"{r['url']}{suffix}")
            except: pass

        unique_queries = list(set([t for t in raw_titles if t and len(t) > 2]))[:2]

        if media_type == 'tv':
            for q_term in unique_queries:
                executor.submit(api_search_worker, megakino_search, f"{q_term} Staffel {season}", "", f"?episode={episode}", 'tv')
                executor.submit(api_search_worker, query_s_to, q_term, "https://s.to", f"/staffel-{season}/episode-{episode}", 'tv')
                executor.submit(api_search_worker, aniworld_search, q_term, "https://aniworld.to", f"/staffel-{season}/episode-{episode}", 'tv')
        else:
            for q_term in unique_queries:
                executor.submit(api_search_worker, megakino_search, q_term, "", "", 'movie')
            
        try:
            # Bis zu 14.5 Sekunden auf echten VOE / Vidoza Stream warten
            result = q.get(timeout=14.5)
            if result:
                result["mode"] = "direct"
                return jsonify(result)
        except queue.Empty: pass
    except Exception as e:
        print(f"[*] Smart Play Info: {e}")
    finally:
        # Nicht blockieren - Hintergrund-Threads sofort abbrechen!
        executor.shutdown(wait=False, cancel_futures=True)

    # FALLBACK: Wenn kein direkter Hoster-Stream gefunden wurde, sofort Backup Server ausliefern
    if tmdb_id:
        if media_type == 'tv':
            fallback_embed = f"https://multiembed.mov/?video_id={tmdb_id}&tmdb=1&s={season}&e={episode}"
            alt_embed = f"https://vidsrc.me/embed/tv?tmdb={tmdb_id}&season={season}&episode={episode}"
        else:
            fallback_embed = f"https://multiembed.mov/?video_id={tmdb_id}&tmdb=1"
            alt_embed = f"https://vidsrc.me/embed/movie?tmdb={tmdb_id}"
        
        return jsonify({
            "mode": "embed",
            "fallback": True,
            "embed_url": fallback_embed,
            "alt_embed_url": alt_embed,
            "title": title,
            "message": "Stream auf Backup-Server geladen"
        }), 200

    return jsonify({"error": "Konnte keinen funktionierenden Stream finden."}), 404


@app.route('/api/get_video')
def get_video():
    """Fallback für direkte URL Eingaben"""
    url = request.args.get('url')
    if not url: return jsonify({"error": "Bitte eine URL übergeben"}), 400
    try:
        provider = resolve_provider(url)
        ep = provider.episode_cls(url=url, selected_language="German", selected_provider="VOE")
        stream_url = ep.stream_url
        if not stream_url: return jsonify({"error": "Konnte keinen Stream-Link finden."}), 400
        return jsonify({"original_url": url, "stream_url": stream_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- WATCH PARTY (GEMEINSAM SCHAUEN) SYSTEM ---
import time
import random
import string

watch_rooms = {}

def cleanup_old_rooms():
    now = time.time()
    to_delete = [rid for rid, r in watch_rooms.items() if now - r.get('last_updated', now) > 18000]
    for rid in to_delete:
        watch_rooms.pop(rid, None)

@app.route('/api/party/create', methods=['POST'])
def party_create():
    cleanup_old_rooms()
    data = request.get_json(force=True, silent=True) or {}
    room_id = "FINN-" + "".join(random.choices(string.digits, k=3))
    while room_id in watch_rooms:
        room_id = "FINN-" + "".join(random.choices(string.digits, k=3))

    watch_rooms[room_id] = {
        'room_id': room_id,
        'movie': data.get('movie', {}),
        'host': data.get('host', 'Finn'),
        'state': 'playing',
        'current_time': float(data.get('time', 0)),
        'season': int(data.get('season', 1)),
        'episode': int(data.get('episode', 1)),
        'last_updated': time.time(),
        'members': 1
    }
    return jsonify({'success': True, 'room': watch_rooms[room_id]})

@app.route('/api/party/status', methods=['GET'])
def party_status():
    cleanup_old_rooms()
    room_id = request.args.get('room_id', '').strip().upper()
    room = watch_rooms.get(room_id)
    if not room:
        return jsonify({'success': False, 'error': 'Raum nicht gefunden'}), 404
    return jsonify({'success': True, 'room': room})

@app.route('/api/party/update', methods=['POST'])
def party_update():
    data = request.get_json(force=True, silent=True) or {}
    room_id = data.get('room_id', '').strip().upper()
    room = watch_rooms.get(room_id)
    if not room:
        return jsonify({'success': False, 'error': 'Raum nicht gefunden'}), 404

    if 'action' in data:
        room['state'] = 'playing' if data['action'] == 'play' else 'paused'
    if 'time' in data:
        room['current_time'] = float(data['time'])
    if 'season' in data:
        room['season'] = int(data['season'])
    if 'episode' in data:
        room['episode'] = int(data['episode'])
    if 'movie' in data and data['movie']:
        room['movie'] = data['movie']

    room['last_updated'] = time.time()
    return jsonify({'success': True, 'room': room})

@app.route('/api/tunnel_info')
def tunnel_info():
    tunnel_file = os.path.join(os.path.dirname(__file__), 'tunnel_url.txt')
    url = None
    if os.path.exists(tunnel_file):
        try:
            with open(tunnel_file, 'r', encoding='utf-8') as f:
                url = f.read().strip()
        except Exception:
            pass
    return jsonify({'tunnel_url': url})

voting_sessions = {}

def cleanup_old_votes():
    now = time.time()
    to_delete = [vid for vid, v in voting_sessions.items() if now - v.get('created_at', now) > 86400]
    for vid in to_delete:
        voting_sessions.pop(vid, None)

@app.route('/api/vote/create', methods=['POST'])
def vote_create():
    cleanup_old_votes()
    data = request.get_json(force=True, silent=True) or {}
    vote_id = "VOTE-" + "".join(random.choices(string.digits, k=3))
    while vote_id in voting_sessions:
        vote_id = "VOTE-" + "".join(random.choices(string.digits, k=3))

    movies_raw = data.get('movies', [])
    movies_list = []
    for m in movies_raw:
        movies_list.append({
            'movie': m,
            'upvotes': 0,
            'downvotes': 0
        })

    voting_sessions[vote_id] = {
        'vote_id': vote_id,
        'title': data.get('title', 'Was schauen wir heute?'),
        'host': data.get('host', 'Finn'),
        'movies': movies_list,
        'created_at': time.time(),
        'total_voters': 0
    }
    return jsonify({'success': True, 'session': voting_sessions[vote_id]})

@app.route('/api/vote/status', methods=['GET'])
def vote_status():
    cleanup_old_votes()
    vote_id = request.args.get('vote_id', '').strip().upper()
    session = voting_sessions.get(vote_id)
    if not session:
        return jsonify({'success': False, 'error': 'Abstimmung nicht gefunden'}), 404
    return jsonify({'success': True, 'session': session})

@app.route('/api/vote/cast', methods=['POST'])
def vote_cast():
    data = request.get_json(force=True, silent=True) or {}
    vote_id = data.get('vote_id', '').strip().upper()
    movie_id = data.get('movie_id')
    choice = data.get('choice', 'up')

    session = voting_sessions.get(vote_id)
    if not session:
        return jsonify({'success': False, 'error': 'Abstimmung nicht gefunden'}), 404

    found = False
    for item in session['movies']:
        if str(item['movie'].get('id')) == str(movie_id):
            if choice == 'up':
                item['upvotes'] += 1
            else:
                item['downvotes'] += 1
            found = True
            break

    if found:
        session['total_voters'] += 1

    return jsonify({'success': True, 'session': session})

# ==============================================================================
# KEY MANAGEMENT & ZUGANGSSCHLUESSEL SYSTEM
# ==============================================================================
KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keys.json')
DEFAULT_ADMIN_KEY = os.environ.get('ADMIN_MASTER_KEY', 'FINN-ADMIN-2026')

def load_keys():
    if not os.path.exists(KEYS_FILE):
        default_keys = [
            {
                "key": "FINN-STREAM-2026",
                "label": "Hauptzugang",
                "created_at": time.strftime("%Y-%m-%d %H:%M"),
                "active": True,
                "uses": 0
            },
            {
                "key": "FINN-VIP-7788",
                "label": "VIP Freunde",
                "created_at": time.strftime("%Y-%m-%d %H:%M"),
                "active": True,
                "uses": 0
            }
        ]
        save_keys(default_keys)
        return default_keys
    try:
        with open(KEYS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_keys(keys_data):
    try:
        with open(KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(keys_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Fehler beim Speichern von keys.json: {e}")

@app.route('/api/keys/verify', methods=['POST'])
def api_verify_key():
    data = request.get_json(force=True, silent=True) or {}
    user_key = (data.get('key') or '').strip().upper()
    if not user_key:
        return jsonify({'success': False, 'valid': False, 'message': 'Kein Schlüssel übergeben'}), 400

    if user_key == DEFAULT_ADMIN_KEY:
        return jsonify({
            'success': True,
            'valid': True,
            'is_admin': True,
            'label': 'Administrator Master Key'
        })

    keys = load_keys()
    for item in keys:
        if item.get('key', '').upper() == user_key:
            if not item.get('active', True):
                return jsonify({'success': False, 'valid': False, 'message': 'Dieser Schlüssel wurde deaktiviert'}), 403
            item['uses'] = item.get('uses', 0) + 1
            item['last_used'] = time.strftime("%Y-%m-%d %H:%M")
            save_keys(keys)
            return jsonify({
                'success': True,
                'valid': True,
                'is_admin': False,
                'label': item.get('label', 'Freigeschaltet')
            })

    return jsonify({'success': False, 'valid': False, 'message': 'Ungültiger Zugangsschlüssel'}), 401

@app.route('/api/keys/admin/login', methods=['POST'])
def api_admin_login():
    data = request.get_json(force=True, silent=True) or {}
    master_key = (data.get('master_key') or '').strip()
    if master_key == DEFAULT_ADMIN_KEY:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Falscher Admin-Master-Schlüssel'}), 401

@app.route('/api/keys/admin/list', methods=['POST'])
def api_admin_list_keys():
    data = request.get_json(force=True, silent=True) or {}
    if data.get('master_key') != DEFAULT_ADMIN_KEY:
        return jsonify({'success': False, 'error': 'Nicht autorisiert'}), 401
    return jsonify({'success': True, 'keys': load_keys(), 'admin_key': DEFAULT_ADMIN_KEY})

@app.route('/api/keys/admin/create', methods=['POST'])
def api_admin_create_key():
    data = request.get_json(force=True, silent=True) or {}
    if data.get('master_key') != DEFAULT_ADMIN_KEY:
        return jsonify({'success': False, 'error': 'Nicht autorisiert'}), 401

    custom_key = (data.get('custom_key') or '').strip().upper()
    label = (data.get('label') or 'Freund').strip()

    if not custom_key:
        part1 = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        part2 = "".join(random.choices(string.digits, k=4))
        custom_key = f"FINN-{part1}-{part2}"

    keys = load_keys()
    if any(k.get('key', '').upper() == custom_key for k in keys):
        return jsonify({'success': False, 'error': 'Dieser Schlüssel existiert bereits'}), 400

    new_entry = {
        'key': custom_key,
        'label': label,
        'created_at': time.strftime("%Y-%m-%d %H:%M"),
        'active': True,
        'uses': 0
    }
    keys.insert(0, new_entry)
    save_keys(keys)
    return jsonify({'success': True, 'key': new_entry})

@app.route('/api/keys/admin/toggle', methods=['POST'])
def api_admin_toggle_key():
    data = request.get_json(force=True, silent=True) or {}
    if data.get('master_key') != DEFAULT_ADMIN_KEY:
        return jsonify({'success': False, 'error': 'Nicht autorisiert'}), 401

    target_key = (data.get('key') or '').strip().upper()
    keys = load_keys()
    found = False
    for k in keys:
        if k.get('key', '').upper() == target_key:
            k['active'] = not k.get('active', True)
            found = True
            break

    if not found:
        return jsonify({'success': False, 'error': 'Schlüssel nicht gefunden'}), 404

    save_keys(keys)
    return jsonify({'success': True, 'keys': keys})

@app.route('/api/keys/admin/delete', methods=['POST'])
def api_admin_delete_key():
    data = request.get_json(force=True, silent=True) or {}
    if data.get('master_key') != DEFAULT_ADMIN_KEY:
        return jsonify({'success': False, 'error': 'Nicht autorisiert'}), 401

    target_key = (data.get('key') or '').strip().upper()
    keys = load_keys()
    keys = [k for k in keys if k.get('key', '').upper() != target_key]
    save_keys(keys)
    return jsonify({'success': True, 'keys': keys})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=========================================================")
    print("Starte DEIN EIGENES STREAMING PROJEKT (Smart Backend)")
    print(f"Server laeuft auf Port: {port}")
    print("=========================================================")
    
    # Pruefe ob Waitress verfuegbar ist (robuster Produktions-Server)
    use_waitress = os.environ.get('USE_WAITRESS', '1') == '1'
    if use_waitress:
        try:
            from waitress import serve
            print(f"[*] Starte stabilen Produktions-Server (Waitress) auf Port {port}...")
            serve(app, host='0.0.0.0', port=port, threads=12)
        except ImportError:
            print("[*] Starte Standard Flask-Server...")
            app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
    else:
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
