"""Conservative first-match analysis; never guess Geo database intersections."""
import ipaddress
from engine.routing_rules import normalize_rule


def overlaps(earlier, later):
    a, b = earlier['value'].lower(), later['value'].lower()
    x, y = earlier['kind'], later['kind']
    if x == y and a == b:
        return 'covered'
    if x == y == 'suffix':
        if b.endswith('.' + a):return 'covered'
        if a.endswith('.' + b):return 'partial'
    if x == y == 'keyword':
        if a in b:return 'covered'
        if b in a:return 'partial'
    if x == 'keyword' and y == 'suffix' and a in b:return 'covered'
    if x == 'suffix' and y == 'keyword' and b in a:return 'partial'
    if x == y == 'cidr':
        first, second = earlier['_network'], later['_network']
        if first.version == second.version and first.overlaps(second):
            return 'covered' if second.subnet_of(first) else 'partial'
    return None


def analyze(rules):
    if not isinstance(rules, list) or len(rules) > 1000:
        raise ValueError('Допускается до 1000 правил')
    normalized = [normalize_rule(r) for r in rules]
    for rule in normalized:
        if rule['kind'] == 'cidr':rule['_network'] = ipaddress.ip_network(rule['value'])
    results = {}
    enabled = []
    for rule in normalized:
        if not rule['enabled']:continue
        matches = []
        for previous in enabled:
            relation = overlaps(previous, rule)
            if relation:
                matches.append(dict(id=previous['id'], relation=relation,
                                    different_destination=previous['destination'] != rule['destination']))
                # A complete earlier match wins; later matches add no explanation.
                if relation == 'covered':break
        if matches:results[rule['id']] = matches[:5]
        enabled.append(rule)
    return results
