"""Loopback-only interface; uploaded CSVs are processed in memory."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from keystroke_model import predict
from identity_model import predict_identity, public_description, replay_identity


def serve(model=None, port=8765, additional_models=None, identity_model=None):
    page_path = Path(__file__).with_name("index.html")
    identity_page = page_path.with_name("identity.html")
    recorder_path = Path(__file__).resolve().parents[2] / "extension" / "recorder.js"
    if identity_model is None:
        identity_path = page_path.parent / "models" / "identity.json"
        if identity_path.exists():
            identity_model = json.loads(identity_path.read_text(encoding="utf-8"))
    if model is None and identity_model is None:
        raise ValueError("Train an identity or baseline model first.")
    default_method = model.get("method", "baseline") if model else None
    models = ({default_method: model} if model else {}) | (additional_models or {})

    def describe_models():
        return [{"id": method, "label": "kNN neighbours" if method == "knn" else "Personal baseline",
                 "window_size": m["window_size"],
                 "k": next(iter(m["profiles"].values())).get("k") if m["profiles"] else None,
                 "profiles": [{"participant": p["participant"], "text_type": p["text_type"],
                               "validation": p["validation"], "training_windows": p["training_windows"]}
                              for p in m["profiles"].values()]} for method, m in models.items()]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, body, content_type="application/json"):
            if isinstance(body, dict):
                body = json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def local_request(self):
            return (self.headers.get("Host") in {f"localhost:{port}", f"127.0.0.1:{port}"}
                    and self.headers.get("Origin") in {None, f"http://localhost:{port}", f"http://127.0.0.1:{port}"})

        def do_GET(self):
            if not self.local_request():
                return self.respond(403, {"error": "Local requests only."})
            if self.path == "/":
                return self.respond(200, (page_path if model else identity_page).read_bytes(), "text/html")
            if self.path == "/identity":
                return self.respond(200, identity_page.read_bytes(), "text/html")
            if self.path == "/identity/recorder.js" and recorder_path.exists():
                return self.respond(200, recorder_path.read_bytes(), "text/javascript")
            if self.path == "/api/identity/profiles":
                if identity_model is None:
                    return self.respond(503, {"error": "Run identity-demo.cmd to train member profiles and start the demo."})
                return self.respond(200, public_description(identity_model, recorder_path.exists()))
            if self.path == "/api/profiles":
                return self.respond(200, {"default_model": default_method, "models": describe_models(),
                    "window_size": model["window_size"] if model else None, "profiles": [
                    {"participant": p["participant"], "text_type": p["text_type"],
                     "validation": p["validation"], "training_windows": p["training_windows"]}
                    for p in (model["profiles"].values() if model else [])]})
            self.respond(404, {"error": "Not found."})

        def do_POST(self):
            if not self.local_request():
                return self.respond(403, {"error": "Local requests only."})
            if self.path not in {"/api/predict", "/api/identity/predict", "/api/identity/replay"}:
                return self.respond(404, {"error": "Not found."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 12 * 1024 * 1024:
                    return self.respond(413, {"error": "Choose a CSV smaller than 12 MB."})
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Request must be a JSON object.")
                if self.path.startswith("/api/identity/"):
                    if identity_model is None:
                        raise ValueError("Identity models are unavailable. Run identity-demo.cmd.")
                    if self.path == "/api/identity/replay":
                        return self.respond(200, replay_identity(identity_model, data.get("replay_id"), data.get("expected_participant")))
                    if not isinstance(data.get("csv"), str):
                        raise ValueError("Request must include CSV text.")
                    return self.respond(200, predict_identity(identity_model, data["csv"], data.get("expected_participant")))
                if not isinstance(data.get("csv"), str):
                    raise ValueError("Request must include CSV text.")
                method = data.get("model", default_method)
                if method not in models:
                    raise ValueError("Selected model is unavailable. Restart the server after training both models.")
                self.respond(200, predict(models[method], data["csv"]))
            except (ValueError, KeyError, TypeError, UnicodeError) as e:
                self.respond(400, {"error": str(e)})

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Typing Lab is ready: http://127.0.0.1:{port}", flush=True)
        print("Open that address in your browser. Ctrl+C stops the server.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
