"""Private desktop child process: bound loopback socket + stdin lifetime."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading

import uvicorn


def main() -> None:
    token = os.environ.get("BECOMING_SERVICE_TOKEN", "")
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise SystemExit("Desktop service requires a private session credential")
    # Import only after the child environment has been checked.
    from .api import app

    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=0, access_log=False,
        timeout_graceful_shutdown=8, log_level="warning",
    ))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)

        def watch_parent() -> None:
            try:
                # The owning desktop process retains the pipe until shutdown.
                sys.stdin.buffer.read()
            finally:
                server.should_exit = True

        threading.Thread(target=watch_parent, daemon=True).start()
        print("BECOMING_BOUND " + json.dumps({
            "port": listener.getsockname()[1], "api_version": "1",
        }), flush=True)
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
