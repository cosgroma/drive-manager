from __future__ import annotations

import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import signal
import threading
from urllib.parse import urlsplit, parse_qs

from .core import Store

STATIC = Path(__file__).parent / "static"


def make_server(store, port=8871, peers=None):
    token = secrets.token_urlsafe(32)
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_peers = peers or {'127.0.0.1'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Paths, tokens and drive names do not need to be recorded in access logs.
            pass

        def reply(self, status, data, mime="application/json"):
            body = json.dumps(data).encode() if mime == "application/json" else data
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") in allowed and self.client_address[0] in allowed_peers

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {"error": "Use localhost or 127.0.0.1"})
            path = urlsplit(self.path).path
            if path == "/api/session":
                return self.reply(200, {"token": token})
            if path == "/api/control-state":
                data=store.snapshot(include_inventory=False)
                data["token"]=token
                return self.reply(200,data)
            if path == "/api/state":
                data = store.snapshot()
                data["token"] = token
                return self.reply(200, data)
            if path == "/api/health":
                return self.reply(200, {"ok": True, "workers": {t.name: t.is_alive() for t in store.threads}})
            if path == "/api/workspace/catalog":
                from .workspaces import catalog
                return self.reply(200, catalog(store))
            if path == '/api/workspace/sources':
                from .sources import search
                params=parse_qs(urlsplit(self.path).query)
                try:
                    return self.reply(200,search(store,query=params.get('q',[''])[0],root=params.get('root',['all'])[0],
                                                 coverage=params.get('coverage',['all'])[0],offset=params.get('offset',[0])[0],limit=params.get('limit',[50])[0]))
                except (ValueError,OSError) as exc:return self.reply(400,{'error':str(exc)})
            if path == "/api/workspace/manifests":
                from .manifests import catalog
                return self.reply(200, catalog(store))
            if path == "/api/workspace/comparisons":
                from .manifests import comparisons
                return self.reply(200, comparisons(store))
            if path == '/api/workspace/snapshots':
                from .snapshots import catalog
                return self.reply(200, catalog(store))
            if path == "/api/workspace/relocations":
                from .relocations import catalog
                return self.reply(200, catalog(store))
            if path == "/api/workspace/registry":
                from .registry import catalog
                return self.reply(200, catalog(store))
            if path == "/api/workspace/manifest/files":
                from .manifests import browse
                params = parse_qs(urlsplit(self.path).query)
                try:
                    return self.reply(200, browse(store, params.get('id',[''])[0], params.get('q',[''])[0]))
                except (ValueError, OSError) as exc:
                    return self.reply(400, {'error': str(exc)})
            if path == "/workspace-review":
                report = store.state / "workspace-review" / "report.html"
                if report.is_file():
                    return self.reply(200, report.read_bytes(), "text/html")
                return self.reply(404, {"error": "Workspace review has not been generated yet"})
            files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                     "/workspace-archive": ("workspace.html", "text/html"),
                     "/workspace.js": ("workspace.js", "text/javascript"),
                     "/style.css": ("style.css", "text/css")}
            if path in files:
                file, mime = files[path]
                return self.reply(200, (STATIC / file).read_bytes(), mime)
            return self.reply(404, {"error": "Not found"})

        def do_POST(self):
            if not self.valid_host() or not secrets.compare_digest(self.headers.get("X-Drive-Token", ""), token):
                return self.reply(403, {"error": "Refresh the local page before making changes"})
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + host for host in allowed}:
                return self.reply(403, {"error": "Requests must come from this local page"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 65536:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                path = urlsplit(self.path).path
                if path == "/api/scan":
                    result = store.scan(data["path"], data.get("depth", -1))
                elif path == '/api/workspace/history':
                    from .workspaces import enqueue_history
                    result = enqueue_history(store, data['source'])
                elif path == '/api/workspace/native-file-snapshot':
                    from .native_files import enqueue
                    result = enqueue(store, data['manifest'], data.get('archive_root'), data.get('preserve_wsl_file_links',False), data.get('preserve_native_link_records',False))
                elif path == '/api/workspace/snapshot':
                    from .snapshots import enqueue
                    result = enqueue(store, data['manifests'], data.get('archive_root'), data.get('preserve_mixed_ownership', False), data.get('materialize_external_hardlinks', False))
                elif path == '/api/workspace/postgres-snapshot':
                    from .protected_snapshots import enqueue
                    result = enqueue(store, data['seal_path'], data['seal_sha256'], data.get('archive_root'), data.get('cluster_relative', '.'))
                elif path == '/api/workspace/manifest':
                    from .manifests import enqueue_manifest
                    result = enqueue_manifest(store, data['source'], data.get('preserve_wsl_file_links',False), data.get('preserve_native_link_records',False))
                elif path == '/api/workspace/compare':
                    scope=data.get('scope','full')
                    if scope=='full':
                        from .snapshot_comparisons import compare
                    elif scope=='working':
                        from .manifests import compare
                    else:raise ValueError('Choose full or working comparison scope')
                    result=compare(store,data['left'],data['right'])
                elif path == '/api/workspace/archive':
                    from .relocations import propose
                    result = propose(store, data['manifest'])
                elif path == '/api/workspace/restore':
                    from .relocations import enqueue_restore
                    result = enqueue_restore(store, data['id'])
                elif path == '/api/workspace/restore/review':
                    from .relocations import propose_reviewed_restore
                    result = propose_reviewed_restore(store,data['id'],data['manifest'])
                elif path == '/api/compare':
                    result = store.compare(data['source'], data['other'])
                elif path == '/api/schedule':
                    result = store.schedule(data['path'], data.get('depth', -1), data.get('interval', 86400))
                elif path == "/api/propose":
                    result = store.propose(data["source"], data["destination"], data.get("action", "copy"))
                elif path == "/api/approve":
                    result = store.approve(data["ids"])
                elif path == "/api/reject":
                    result = store.reject(data["ids"])
                elif path == "/api/control":
                    result = store.control(data["id"], data["action"])
                elif path == "/api/policy":
                    result = store.policy(data["source"], data["destination"], data["action"],
                                          data.get("references_confirmed", False), data.get("automatic", True))
                elif path == "/api/policy/remove":
                    with store.db() as db:
                        db.execute("DELETE FROM policies WHERE id=?", (data["id"],))
                    store.event("Standing policy removed; already authorized jobs remain in the queue")
                    result = None
                elif path == '/api/purge/propose':
                    result = store.propose_purge(data['id'])
                else:
                    return self.reply(404, {"error": "Not found"})
                self.reply(200, {"ok": True, "id": result})
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.reply(400, {"error": str(exc)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    # Support ephemeral ports in tests.
    allowed.update({f"127.0.0.1:{server.server_port}", f"localhost:{server.server_port}"})
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description="Drive Manager — local review and durable workers")
    parser.add_argument("--state", default=str(Path.home() / ".local/share/drive-manager"))
    parser.add_argument("--port", type=int, default=8871)
    args = parser.parse_args()
    store = Store(args.state)
    lock = open(store.state / "service.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("A service already owns this state directory")
    server = make_server(store, args.port)
    store.start()

    def shutdown(*_):
        store.stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"Drive Manager: http://localhost:{server.server_port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        store.stop.set()
        for thread in store.threads:
            thread.join(timeout=10)
        server.server_close()
        lock.close()


if __name__ == "__main__":
    main()
