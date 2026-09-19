"""Ordered Mihomo rules. Legacy application routes remain independent and intact."""
import copy
import ipaddress
import re
import uuid
from urllib.parse import urlsplit

KINDS = {'process':'PROCESS-NAME','geosite':'GEOSITE','suffix':'DOMAIN-SUFFIX',
         'keyword':'DOMAIN-KEYWORD','geoip':'GEOIP','cidr':'IP-CIDR'}
BLOCKED_PROCESSES = {'system.exe','svchost.exe','lsass.exe','services.exe','wininit.exe',
                    'sadnessvpn.exe','sing-box.exe','mihomo.exe','winws.exe'}


def normalize_rule(raw):
    if not isinstance(raw, dict):
        raise ValueError('Некорректное правило')
    kind, value = raw.get('kind'), raw.get('value')
    if kind not in KINDS or not isinstance(value, str) or not 0 < len(value.strip()) <= 253:
        raise ValueError('Укажите тип и значение правила')
    value = value.strip()
    if any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError('Значение содержит управляющие символы')
    if kind == 'suffix':
        parsed = urlsplit(value if '://' in value else '//' + value)
        if parsed.username or parsed.password:
            raise ValueError('Домен не должен содержать логин или пароль')
        value = (parsed.hostname or '').rstrip('.').encode('idna').decode('ascii').lower()
        if not value or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p) for p in value.split('.')):
            raise ValueError('Некорректный домен')
    elif kind == 'cidr':
        try:
            value = str(ipaddress.ip_network(value, strict=False))
        except ValueError:
            raise ValueError('Некорректный IP или маска CIDR') from None
    elif kind == 'process':
        if not re.fullmatch(r'[^\\/:*?"<>|,()\s][^\\/:*?"<>|,()\r\n]*\.exe', value, re.I) or value.lower() in BLOCKED_PROCESSES:
            raise ValueError('Укажите имя пользовательского приложения .exe')
    elif kind in {'geoip', 'geosite'}:
        if not re.fullmatch(r'[a-zA-Z0-9_-]+(?:@[a-zA-Z0-9_-]+)?', value):
            raise ValueError('Некорректное имя категории')
        value = value.lower()
    elif not re.fullmatch(r'[a-zA-Z0-9._-]+', value):
        raise ValueError('Введите часть доменного имени')
    destination = raw.get('destination', 'proxy')
    if not isinstance(destination, str) or not (destination in {'proxy', 'direct'} or re.fullmatch(r'server:[a-zA-Z0-9_-]{1,128}', destination)):
        raise ValueError('Некорректное назначение')
    name = raw.get('name', '')
    if not isinstance(name, str) or len(name) > 256:
        raise ValueError('Слишком длинное название')
    enabled = raw.get('enabled', True)
    if not isinstance(enabled, bool):
        raise ValueError('Некорректное состояние правила')
    identity = raw.get('id') or str(uuid.uuid4())
    if not isinstance(identity, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', identity):
        raise ValueError('Некорректный ID правила')
    return dict(id=identity, kind=kind, value=value, name=name.strip() or value,
                destination=destination, enabled=enabled)


def resolve_rules(rules, groups):
    from engine.app_routes import assignments
    result = []
    for raw in rules:
        rule = normalize_rule(raw)
        if not rule['enabled']:
            continue
        destination = rule['destination']
        route = {'tag': 'proxy', 'server': None}
        if destination != 'proxy':
            route = assignments([{'exe':'rule.exe','destination':destination}], groups)[0]
        rule_type = KINDS[rule['kind']]
        if rule['kind'] == 'cidr' and ':' in rule['value']:
            rule_type = 'IP-CIDR6'
        result.append({**route, 'match': f"{rule_type},{rule['value']}"})
    return result


def validate_rules(rules, groups):
    if not isinstance(rules, list) or len(rules) > 1000:
        raise ValueError('Допускается до 1000 правил')
    normalized = [normalize_rule(r) for r in rules]
    from engine.geo_catalog import categories
    for rule in normalized:
        if rule['kind'] in {'geosite', 'geoip'} and rule['value'] not in categories(rule['kind']):
            raise ValueError('Категория отсутствует в локальной базе. Выберите значение из списка.')
    if len({r['id'] for r in normalized}) != len(normalized):
        raise ValueError('Повторяющийся ID правила')
    resolve_rules(normalized, groups)
    return normalized
