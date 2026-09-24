"""One command for the live WhatsApp demo: check everything, open a tunnel, point Meta at it, run.

    python -m reach_agent.live [--llm deepseek] [--port 8000]      (on Windows: .\\demo.ps1)

Reads the Meta settings from live.env (never committed; copy live.env.example). Before anything
starts it checks the access token (and how long it has left), the App secret, the phone number and
the port, so a problem shows up as one clear line instead of a silent webhook. Then it starts a
cloudflared quick tunnel, subscribes the app's webhook to the tunnel's new address, and runs one
conversation after another until /sair or Ctrl+C, which also closes the tunnel.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from .agent import ReachAgent
from .cli import make_extractor
from .clinic_calendar import Calendar
from .llm import PROVIDERS
from .whatsapp_demo import _read_terminal, _serve, _transport, run
from .whatsapp_meta import GRAPH_API

SETTINGS_FILE = Path("live.env")
REQUIRED = ("META_ACCESS_TOKEN", "META_PHONE_NUMBER_ID", "META_APP_SECRET", "META_VERIFY_TOKEN",
            "META_APP_ID", "META_WABA_ID")
CLOUDFLARED_WINDOWS = Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe")
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class SetupError(Exception):
    """Something to fix before the demo can start; the message says what and how."""


def load_settings(path: Path = SETTINGS_FILE, environ: dict | None = None) -> dict[str, str]:
    """KEY=VALUE lines from `path` (comments and blanks skipped); the environment wins over the file."""
    environ = os.environ if environ is None else environ
    settings: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                settings[key.strip()] = value.strip().strip('"').strip("'")
    settings.update({key: environ[key].strip() for key in REQUIRED if environ.get(key)})
    missing = [key for key in REQUIRED if not settings.get(key) or "..." in settings[key]]
    if missing:
        raise SetupError(f"Falta preencher em {path}: {', '.join(missing)} (vê live.env.example).")
    return settings


def check_meta(settings: dict[str, str], http) -> str:
    """Verify every Meta setting before starting. Returns the test number to message."""
    app_token = f"{settings['META_APP_ID']}|{settings['META_APP_SECRET']}"
    bearer = {"Authorization": f"Bearer {settings['META_ACCESS_TOKEN']}"}

    if http.get(f"{GRAPH_API}/{settings['META_APP_ID']}", params={"access_token": app_token}).is_error:
        raise SetupError("O App secret (ou o App ID) está errado. Copia-o de App settings → Basic.")

    token = http.get(f"{GRAPH_API}/debug_token", params={"input_token": settings["META_ACCESS_TOKEN"],
                                                        "access_token": app_token}).json().get("data", {})
    if not token.get("is_valid"):
        raise SetupError("O access token expirou ou é inválido. Gera outro em Use cases → Customize → "
                         "Step 1. Try it out → Generate token, e põe-no em live.env.")
    expires = token.get("expires_at") or 0  # 0 means it never expires (a system user token)
    if expires:
        minutes = int((datetime.fromtimestamp(expires) - datetime.now()).total_seconds() // 60)
        print(f"  token válido por mais {minutes // 60} h {minutes % 60} min")

    phone = http.get(f"{GRAPH_API}/{settings['META_PHONE_NUMBER_ID']}", headers=bearer,
                     params={"fields": "display_phone_number"})
    if phone.is_error:
        raise SetupError("O META_PHONE_NUMBER_ID não pertence a este token. Copia o Phone Number ID do Step 1.")

    subscribed = http.get(f"{GRAPH_API}/{settings['META_WABA_ID']}/subscribed_apps", headers=bearer).json()
    if settings["META_APP_ID"] not in {app.get("whatsapp_business_api_data", {}).get("id")
                                       for app in subscribed.get("data", [])}:
        # without this the test WhatsApp account never calls our webhook
        if http.post(f"{GRAPH_API}/{settings['META_WABA_ID']}/subscribed_apps", headers=bearer).is_error:
            raise SetupError("Não consegui ligar a conta de WhatsApp de teste à app (META_WABA_ID certo?).")
        print("  conta de WhatsApp de teste ligada à app")
    return phone.json()["display_phone_number"]


def point_webhook(settings: dict[str, str], url: str, http, attempts: int = 6, wait: float = 5) -> None:
    """Subscribe the app's webhook to `url`. Meta checks the URL at once, and a brand-new tunnel
    address can take a few seconds to resolve, so this retries."""
    data = {"object": "whatsapp_business_account", "fields": "messages", "callback_url": url,
            "verify_token": settings["META_VERIFY_TOKEN"],
            "access_token": f"{settings['META_APP_ID']}|{settings['META_APP_SECRET']}"}
    reply = None
    for attempt in range(attempts):
        reply = http.post(f"{GRAPH_API}/{settings['META_APP_ID']}/subscriptions", data=data)
        if not reply.is_error and reply.json().get("success"):
            return
        if attempt < attempts - 1:
            time.sleep(wait)
    raise SetupError(f"A Meta não aceitou o webhook {url}: {reply.text if reply is not None else ''}")


def find_tunnel_url(line: str) -> str | None:
    match = TUNNEL_URL.search(line)
    return match.group(0) if match else None


def start_tunnel(port: int, timeout: float = 60) -> tuple[subprocess.Popen, str]:
    """Start a cloudflared quick tunnel to `port`; return it once it has an address and a connection."""
    exe = shutil.which("cloudflared") or (str(CLOUDFLARED_WINDOWS) if CLOUDFLARED_WINDOWS.exists() else None)
    if exe is None:
        raise SetupError("Não encontro o cloudflared. Instala-o: winget install Cloudflare.cloudflared")
    process = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace")
    lines: queue.Queue = queue.Queue()

    def drain() -> None:  # keep reading, or cloudflared blocks once the pipe fills up
        for line in process.stderr:
            lines.put(line)

    threading.Thread(target=drain, daemon=True).start()
    url, connected, deadline = None, False, time.monotonic() + timeout
    while not (url and connected):
        if time.monotonic() > deadline or process.poll() is not None:
            process.terminate()
            raise SetupError("O túnel não arrancou (sem internet?). Tenta outra vez.")
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            continue
        url = url or find_tunnel_url(line)
        connected = connected or "Registered tunnel connection" in line
    return process, url


def _port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def _wait_until_listening(port: int, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while _port_is_free(port):
        if time.monotonic() > deadline:
            raise SetupError(f"O servidor não arrancou na porta {port}.")
        time.sleep(0.2)


def main(argv: list[str] | None = None) -> None:
    import httpx

    parser = argparse.ArgumentParser(description="Demo ao vivo no WhatsApp, com um só comando.")
    parser.add_argument("--llm", choices=sorted(PROVIDERS), metavar="PROVIDER",
                        help=f"usar um LLM ({', '.join(PROVIDERS)}) em vez das regras")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    tunnel = None
    try:
        print("A verificar...")
        settings = load_settings()
        if not _port_is_free(args.port):
            raise SetupError(f"A porta {args.port} está ocupada: fecha a outra demo (ou usa --port 8001).")
        extractor = make_extractor(args.llm)  # a missing LLM key stops here, not mid-conversation
        with httpx.Client(timeout=15) as http:
            number = check_meta(settings, http)
            events: queue.Queue = queue.Queue()
            app, sender = _transport("meta", [settings[key] for key in REQUIRED[:4]],
                                     lambda message: events.put(("whatsapp", message)))
            _serve(app, args.port)
            _wait_until_listening(args.port)
            print("A abrir o túnel...")
            tunnel, url = start_tunnel(args.port)
            print(f"  {url}")
            print("A apontar o webhook da Meta para o túnel...")
            point_webhook(settings, f"{url}/whatsapp", http)

        threading.Thread(target=_read_terminal, args=(events,), daemon=True).start()
        print(f"\nPRONTO. No WhatsApp, escreve para {number}: \"Olá, queria marcar uma consulta\"")
        print(f"Leitor: {extractor.name}. Comandos: /estado, /sem-resposta, /sair (ou Ctrl+C).\n")
        while True:
            sim = run(events, ReachAgent(extractor, Calendar.from_json()), sender)
            if sim is None or not sim.conv.phase.is_terminal:
                break  # /sair
            print("\n--- Pronto para outra conversa (o calendário recomeça) ---\n")
    except SetupError as problem:
        raise SystemExit(f"\nPROBLEMA: {problem}") from None
    except KeyboardInterrupt:
        print("\nA terminar...")
    finally:
        if tunnel is not None:
            tunnel.terminate()


if __name__ == "__main__":
    main()
