"""Lossless XHTTP share-link settings and safe Clash node import."""
import copy
import json

import yaml


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


def mihomo_xhttp(server):
    if server.get("mihomo_xhttp") is not None:
        return copy.deepcopy(server["mihomo_xhttp"])
    settings = copy.deepcopy(server.get("xhttp", {"path": server.get("path") or "/",
                                                  "host": server.get("host_header", "")}))
    extra = settings.pop("extra", {})
    settings.update(extra)
    result = {}
    for key, value in settings.items():
        if key == "xmux":
            unsupported = set(value) - set(_XMUX_KEYS)
            if unsupported:
                raise ValueError("XHTTP XMUX: эти параметры не поддерживаются — " + ", ".join(sorted(unsupported)))
            result["reuse-settings"] = {_XMUX_KEYS[k]: v for k, v in value.items()}
        elif key in _XHTTP_KEYS:
            result[_XHTTP_KEYS[key]] = value
        else:
            raise ValueError(f"XHTTP: параметр {key} не поддерживается. Нужна ссылка без него.")
    return result


def parse_clash_nodes(raw):
    # No object constructors or aliases: aliases can create recursive node graphs.
    for token in yaml.scan(raw):
        if isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)):
            raise ValueError("Подписка YAML с якорями не поддерживается")
    document = yaml.safe_load(raw)
    if not isinstance(document, dict) or not isinstance(document.get("proxies"), list):
        return []
    result = []
    for node in document["proxies"]:
        if not isinstance(node, dict) or node.get("type") not in {"vless", "ss", "trojan", "hysteria2", "hy2"}:
            continue
        if not node.get("server") or not node.get("port"):
            continue
        proto = "hysteria2" if node["type"] == "hy2" else node["type"]
        network = node.get("network", "tcp")
        if network == "splithttp":
            network = "xhttp"
        reality = node.get("reality-opts") or {}
        transport = node.get(network + "-opts") or {}
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
        if network == "xhttp":
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
        result.append(server)
    return result
