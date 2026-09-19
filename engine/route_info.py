"""Summarize only routes actually reported by a core, without leaking endpoints."""
import ntpath
import time


def observed_rule_routes(connections, rules):
    """Match core-reported rule type/payload, not guessed destination traffic."""
    types={'process':'processname','suffix':'domainsuffix','keyword':'domainkeyword',
           'geosite':'geosite','geoip':'geoip','cidr':'ipcidr'}
    matches={}
    for connection in connections:
        reported=str(connection.get('rule','')).replace('-','').lower().replace('ipcidr6','ipcidr')
        payload=str(connection.get('rulePayload','')).lower()
        for rule in rules:
            if rule.get('enabled') is False:continue
            if types.get(rule.get('kind'))!=reported or str(rule.get('value','')).lower()!=payload:continue
            metadata=connection.get('metadata') or {}
            process=ntpath.basename(str(metadata.get('process') or metadata.get('processPath') or ''))[:128]
            chains=[str(c) for c in connection.get('chains',[]) if c in {'DIRECT','proxy'} or str(c).startswith('app-')]
            matches[rule['id']]=dict(id=rule['id'],process=process,exit=chains[0] if chains else 'Не сообщён ядром',observed_at=int(time.time()))
            break
    return list(matches.values())


def observed_app_routes(connections):
    apps = {}
    for connection in connections:
        metadata = connection.get("metadata") or {}
        process = metadata.get("process") or metadata.get("processPath") or ""
        exe = ntpath.basename(str(process)).strip()
        if not exe:
            continue
        chains = {str(value).lower() for value in connection.get("chains", [])}
        route = "proxy" if "proxy" in chains or any(c.startswith("app-") for c in chains) else "direct" if "direct" in chains else "blocked" if chains & {"reject", "block"} else "unknown"
        key = exe.lower()
        if key not in apps:
            apps[key] = {"exe": exe, "routes": set(), "networks": set(), "connections": 0}
        row = apps[key]
        row["routes"].add(route)
        network = str(metadata.get("network", "")).lower()
        if network in {"tcp", "udp"}:
            row["networks"].add(network)
        row["connections"] += 1
    return [{**row, "routes": sorted(row["routes"]), "networks": sorted(row["networks"])}
            for _key, row in sorted(apps.items())][:500]
