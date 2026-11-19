#!/usr/bin/env python3
"""VLESS link → Xray config for the optional `proxy` container (Telegram and OpenRouter go through it).

    python3 deploy/proxy-config.py 'vless://UUID@host:443?type=xhttp&security=tls&sni=…&path=…#name'

Writes deploy/xray/config.json (git-ignored: it contains your UUID). Only the standard library is used,
so it runs on a bare Ubuntu server. Supported: transports tcp, ws, grpc, xhttp (splithttp), httpupgrade;
security tls, reality, none. Inside Docker the proxy listens on http://proxy:10809 (not published outside).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

OUT = Path(__file__).resolve().parent / "xray" / "config.json"
HTTP_PORT = 10809


def _q(params: dict[str, list[str]], key: str, default: str = "") -> str:
    return unquote(params.get(key, [default])[0]).strip()


def build(link: str) -> dict:
    link = link.strip()
    if not link.startswith("vless://"):
        raise SystemExit("Нужна ссылка вида vless://… (из вашего клиента: «Поделиться» / «Копировать ссылку»)")
    url = urlsplit(link)
    if not url.username or not url.hostname or not url.port:
        raise SystemExit("В ссылке не хватает UUID, адреса или порта")
    p = parse_qs(url.query)
    network = _q(p, "type", "tcp").lower()
    if network == "splithttp":
        network = "xhttp"
    security = _q(p, "security", "none").lower()

    user: dict = {"id": unquote(url.username), "encryption": _q(p, "encryption", "none") or "none"}
    if flow := _q(p, "flow"):
        user["flow"] = flow

    stream: dict = {"network": network, "security": security}
    sni = _q(p, "sni") or _q(p, "host") or url.hostname
    fp = _q(p, "fp")
    if security == "tls":
        tls: dict = {"serverName": sni}
        if fp:
            tls["fingerprint"] = fp
        if alpn := _q(p, "alpn"):
            tls["alpn"] = [a for a in alpn.split(",") if a]
        if _q(p, "allowInsecure") in ("1", "true"):
            tls["allowInsecure"] = True
        stream["tlsSettings"] = tls
    elif security == "reality":
        stream["realitySettings"] = {
            "serverName": sni,
            "fingerprint": fp or "chrome",
            "publicKey": _q(p, "pbk"),
            "shortId": _q(p, "sid"),
            "spiderX": _q(p, "spx"),
        }
    elif security not in ("none", ""):
        raise SystemExit(f"security={security} не поддерживается (нужен tls, reality или none)")

    path, host = _q(p, "path"), _q(p, "host")
    if network == "xhttp":
        xhttp: dict = {"path": path or "/", "mode": _q(p, "mode", "auto") or "auto"}
        if host:
            xhttp["host"] = host
        if extra := _q(p, "extra"):
            try:
                xhttp["extra"] = json.loads(extra)
            except json.JSONDecodeError as exc:
                raise SystemExit("Параметр extra в ссылке — не JSON") from exc
        stream["xhttpSettings"] = xhttp
    elif network == "ws":
        stream["wsSettings"] = {"path": path or "/", **({"host": host} if host else {})}
    elif network == "httpupgrade":
        stream["httpupgradeSettings"] = {"path": path or "/", **({"host": host} if host else {})}
    elif network == "grpc":
        stream["grpcSettings"] = {"serviceName": _q(p, "serviceName") or path.lstrip("/")}
    elif network == "tcp":
        if _q(p, "headerType") == "http":
            stream["tcpSettings"] = {"header": {"type": "http", "request": {"path": [path or "/"]}}}
    else:
        raise SystemExit(f"type={network} не поддерживается (tcp, ws, grpc, xhttp, httpupgrade)")

    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "http-in",
                "listen": "0.0.0.0",  # only reachable inside the Docker network: the port is not published
                "port": HTTP_PORT,
                "protocol": "http",
                "settings": {},
            }
        ],
        "outbounds": [
            {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {"vnext": [{"address": url.hostname, "port": url.port, "users": [user]}]},
                "streamSettings": stream,
            }
        ],
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    config = build(sys.argv[1])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT.chmod(0o644)  # the xray image runs as a non-root user and must read it
    ob = config["outbounds"][0]
    s = ob["streamSettings"]
    print(f"Готово: {OUT}")
    print(f"  сервер {ob['settings']['vnext'][0]['address']}:{ob['settings']['vnext'][0]['port']}, {s['network']} + {s['security']}")
    print(f"  в .env: TELEGRAM_PROXY_URL=http://proxy:{HTTP_PORT}, LLM_PROXY_URL=http://proxy:{HTTP_PORT}, COMPOSE_PROFILES=proxy")


if __name__ == "__main__":
    main()
