"""Start the local Chiplet DSE GUI: python gui.py [--port 8765] [--no-browser]."""
import argparse
import threading
import webbrowser
from pathlib import Path
from simple_rapidchiplet.gui_server import Application, make_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    app = Application(Path(__file__).resolve().parent, args.config)
    try:
        server = make_server(app, args.port)
    except OSError as exc:
        parser.exit(1, f"Cannot listen on port {args.port}: {exc}. Try --port 8766.\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Chiplet DSE GUI: {url}\nCtrl+C stops the server.", flush=True)
    if not args.no_browser:
        threading.Timer(.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if app.active_job:
            app.cancel(app.active_job)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
