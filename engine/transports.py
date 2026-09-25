"""Lossless XHTTP share-link settings and safe Clash node import."""
import copy
import json
import logging

import yaml

# Child of the "sadness" journal logger: the root logger has no handler.
_log = logging.getLogger("sadness.transports")


def xhttp_from_query(params):
    settings = {"path": params.get("path") or "/", "host": params.get("host", ""),
                "mode": params.get("mode") or "auto"}
    if params.get("extra"):
        try:
            extra = json.loads(params["extra"])
        except (ValueError, TypeError):
            raise ValueError("XHTTP: extra должен содержать корректный JSON") from None
        if not isinstance(extra, dict):
            raise ValueError("XHTTP: extra должен быть JSON-объектом")
        settings["extra"] = extra
    return settings


_XHTTP_KEYS = {
    "path": "path", "host": "host", "mode": "mode", "headers": "headers",
    "noGRPCHeader": "no-grpc-header", "xPaddingBytes": "x-padding-bytes",
    "xPaddingObfsMode": "x-padding-obfs-mode", "xPaddingKey": "x-padding-key",
    "xPaddingHeader": "x-padding-header", "xPaddingPlacement": "x-padding-placement",
    "xPaddingMethod": "x-padding-method", "uplinkHTTPMethod": "uplink-http-method",
    "sessionPlacement": "session-placement", "sessionKey": "session-key",
    "sessionTable": "session-table", "sessionLength": "session-length",
    "seqPlacement": "seq-placement", "seqKey": "seq-key",
    "uplinkDataPlacement": "uplink-data-placement", "uplinkDataKey": "uplink-data-key",
    "uplinkChunkSize": "uplink-chunk-size", "scMaxEachPostBytes": "sc-max-each-post-bytes",
    "scMinPostsIntervalMs": "sc-min-posts-interval-ms",
}
_XMUX_KEYS = {"maxConcurrency": "max-concurrency", "maxConnections": "max-connections",
              "cMaxReuseTimes": "c-max-reuse-times", "hMaxRequestTimes": "h-max-request-times",
              "hMaxReusableSecs": "h-max-reusable-secs", "hKeepAlivePeriod": "h-keep-alive-period"}
# Xray leaves these in the share link, but they never reach the wire: mihomo.exe
# only declares no-sse-header, sc-max-buffered-posts and sc-stream-up-server-secs
# as inbound options, and scMaxConcurrentPosts / cMaxLifetimeMs merely cap the
# client's own upload concurrency and connection lifetime. The peer never
# negotiates any of them, so dropping them keeps such links usable instead of
# refusing a server that would otherwise connect.
_XHTTP_IGNORED = {"scMaxConcurrentPosts", "scMaxBufferedPosts",
                  "scStreamUpServerSecs", "noSSEHeader"}
_XMUX_IGNORED = {"cMaxLifetimeMs"}


def mihomo_xhttp(server):
    if server.get("mihomo_xhttp") is not None:
        return copy.deepcopy(server["mihomo_xhttp"])
    settings = copy.deepcopy(server.get("xhttp", {"path": server.get("path") or "/",
                                                  "host": server.get("host_header", "")}))
    extra = settings.pop("extra", {})
    settings.update(extra)
    result, ignored = {}, []
    for key, value in settings.items():
        if key == "xmux":
            unsupported = set(value) - set(_XMUX_KEYS) - _XMUX_IGNORED
            if unsupported:
                raise ValueError("XHTTP XMUX: эти параметры не поддерживаются — " + ", ".join(sorted(unsupported)))
            ignored += sorted(set(value) & _XMUX_IGNORED)
            reuse = {_XMUX_KEYS[k]: v for k, v in value.items() if k in _XMUX_KEYS}
            if reuse:
                result["reuse-settings"] = reuse
        elif key in _XHTTP_KEYS:
            result[_XHTTP_KEYS[key]] = value
        elif key in _XHTTP_IGNORED:
            ignored.append(key)
        else:
            raise ValueError(f"XHTTP: параметр {key} не поддерживается. Нужна ссылка без него.")
    if ignored:
        _log.info("XHTTP: у Mihomo нет этих параметров, они пропущены — %s", ", ".join(ignored))
    return result


def parse_clash_nodes(raw, rejected=None):
    """Clash/Mihomo YAML → серверы. Один несовместимый узел не блокирует остальные:
    причина отказа уходит в ``rejected`` (имя узла + объяснение, без секретов)."""
    # No object constructors or aliases: aliases can create recursive node graphs.
    for token in yaml.scan(raw):
        if isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)):
            raise ValueError("Подписка YAML с якорями не поддерживается")
    document = yaml.safe_load(raw)
    if not isinstance(document, dict) or not isinstance(document.get("proxies"), list):
        return []
    result = []
    rejected = [] if rejected is None else rejected
    for node in document["proxies"]:
        if not isinstance(node, dict):
            continue
        label = "".join(c for c in str(node.get("name") or node.get("type") or "узел") if c.isprintable())[:80]
        if node.get("type") not in {"vless", "vmess", "ss", "trojan", "hysteria2", "hy2"}:
            rejected.append({"name": label, "reason": f"протокол {node.get('type')} не поддерживается ядром Mihomo"})
            continue
        if not node.get("server") or not node.get("port"):
            rejected.append({"name": label, "reason": "не указан адрес или порт"})
            continue
        try:
            server = _clash_node(node)
            from engine.core_config import ensure_supported
            ensure_supported(server)
        except (ValueError, TypeError, KeyError) as exc:
            rejected.append({"name": label, "reason": (str(exc) if isinstance(exc, ValueError) else "узел повреждён")[:200]})
            continue
        result.append(server)
    return result


def _clash_node(node):
    proto = "hysteria2" if node["type"] == "hy2" else node["type"]
    network = node.get("network", "tcp")
    if network == "splithttp":
        network = "xhttp"
    reality = node.get("reality-opts") or {}
    transport = node.get(network + "-opts") or {}
    if network == "ws" and transport.get("v2ray-http-upgrade"):
        # Иначе HTTPUpgrade-узел молча превращался в обычный WebSocket.
        network = "httpupgrade"
    headers = transport.get("headers") or {}
    alpn = node.get("alpn") or []
    server = {
        "protocol": proto, "remark": str(node.get("name") or proto),
        "host": str(node["server"]), "port": int(node["port"]), "type": network,
        "security": "reality" if reality else "tls" if node.get("tls") or proto in {"trojan", "hysteria2"} else "none",
        "uuid": str(node.get("uuid", "")), "password": str(node.get("password", "")),
        "method": node.get("cipher", ""), "sni": str(node.get("servername") or node.get("sni") or ""),
        "fp": node.get("client-fingerprint", ""), "pbk": reality.get("public-key", ""),
        "pinned_cert": node.get("fingerprint", ""), "verify_cert_name": node.get("name-cert-verify", ""),
        "sid": str(reality.get("short-id", "")), "flow": node.get("flow", ""),
        "path": transport.get("path", ""), "host_header": transport.get("host") or headers.get("Host", ""),
        "serviceName": transport.get("grpc-service-name", ""),
        "alpn": ",".join(alpn) if isinstance(alpn, list) else str(alpn),
        "allowInsecure": "1" if node.get("skip-cert-verify") else "0",
        "insecure": bool(node.get("skip-cert-verify")), "encryption": node.get("encryption", "none"),
        "obfs": node.get("obfs", ""), "obfs_password": node.get("obfs-password", ""),
    }
    if network == "http":
        # В Clash network: http — это TCP с маскировкой под HTTP/1.1, а не
        # HTTP/2 (type=http в ссылках Xray). Раньше узел молча становился h2.
        paths = transport.get("path") or ["/"]
        hosts = headers.get("Host") or []
        server["type"], server["header_type"] = "tcp", "http"
        server["path"] = str(paths[0] if isinstance(paths, list) else paths)
        server["host_header"] = ",".join(map(str, hosts)) if isinstance(hosts, list) else str(hosts)
    elif isinstance(server["host_header"], list):
        # h2-opts.host в Clash — список; внутренняя модель хранит одно имя.
        server["host_header"] = str(server["host_header"][0]) if server["host_header"] else ""
    if proto == "ss" and node.get("plugin"):
        from engine.core_config import SUPPORTED_SS_PLUGINS
        if node["plugin"] not in SUPPORTED_SS_PLUGINS:
            raise ValueError(f"Shadowsocks: плагин {node['plugin']} не поддерживается ядром Mihomo")
        server["plugin"] = node["plugin"]
        server["plugin_opts"] = copy.deepcopy(node.get("plugin-opts") or {})
    if proto == "vmess":
        # Mihomo собирает VMess нативно; alterId по умолчанию 0 (AEAD).
        try:
            server["alter_id"] = int(node.get("alterId") or 0)
        except (TypeError, ValueError):
            raise ValueError("VMess: alterId должен быть числом") from None
        server["method"] = str(node.get("cipher") or "auto")
    if network == "xhttp":
        if "download-settings" in transport:
            # Как и для ссылок (downloadSettings): отдельный нижний канал XHTTP
            # не поддерживается, сервер отклоняется, а не собирается без него.
            raise ValueError("XHTTP: раздельный канал загрузки (download-settings) не поддерживается")
        server["mihomo_xhttp"] = copy.deepcopy(transport)
    if proto == "hysteria2":
        from engine.hysteria2 import validate, fingerprint
        server["type"] = "quic"
        for source, target in (("ports", "ports"), ("hop-interval", "hop_interval"), ("up", "up"), ("down", "down"), ("ech-opts", "ech"), ("realm-opts", "realm-opts")):
            if node.get(source):
                server[target] = copy.deepcopy(node[source])
        if server.get("pinned_cert"):
            server["pinned_cert"] = fingerprint(server["pinned_cert"])
        validate(server)
    return server
