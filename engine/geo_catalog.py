"""Read category names from bundled V2Ray protobuf lists without network access."""
from functools import lru_cache
from pathlib import Path
from engine.paths import bin_path

DISPLAY_NAMES = {
    'telegram':'Telegram', 'discord':'Discord', 'youtube':'YouTube',
    'google':'Google', 'openai':'OpenAI / ChatGPT', 'anthropic':'Anthropic / Claude',
    'netflix':'Netflix', 'steam':'Steam', 'epicgames':'Epic Games',
    'facebook':'Facebook', 'instagram':'Instagram', 'twitter':'X / Twitter',
    'twitch':'Twitch', 'microsoft':'Microsoft', 'apple':'Apple',
    'private':'Локальные и частные адреса',
    'category-ads-all':'Рекламные домены', 'category-ai-!cn':'AI-сервисы вне Китая',
    'category-games':'Игровые сервисы', 'category-social-media-!cn':'Социальные сети вне Китая',
}
COUNTRY_NAMES = {'ru':'Россия','us':'США','de':'Германия','nl':'Нидерланды',
    'fr':'Франция','gb':'Великобритания','fi':'Финляндия','se':'Швеция',
    'ch':'Швейцария','pl':'Польша','ua':'Украина','by':'Беларусь',
    'kz':'Казахстан','tr':'Турция','cn':'Китай','jp':'Япония',
    'kr':'Южная Корея','sg':'Сингапур','ca':'Канада','au':'Австралия'}


def category_items(kind):
    """Keep unknown technical labels verbatim, without inventing their meaning."""
    return [dict(value=value, name=(COUNTRY_NAMES.get(value) if kind=='geoip' else None)
                 or DISPLAY_NAMES.get(value) or value) for value in categories(kind)]


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data): raise ValueError('Повреждённая база Geo')
        byte = data[offset]; offset += 1; value |= (byte & 127) << shift
        if byte < 128: return value, offset
    raise ValueError('Повреждённая база Geo')


def fields(data):
    offset = 0
    while offset < len(data):
        key, offset = varint(data, offset); wire = key & 7
        if wire == 2:
            size, offset = varint(data, offset); end = offset + size
            if end > len(data): raise ValueError('Повреждённая база Geo')
            yield key >> 3, data[offset:end]; offset = end
        elif wire == 0: _, offset = varint(data, offset)
        elif wire in (1, 5): offset += 8 if wire == 1 else 4
        else: raise ValueError('Неизвестный формат базы Geo')


@lru_cache(maxsize=2)
def categories(kind):
    if kind not in {'geosite','geoip'}: raise ValueError('Неизвестная база')
    data = Path(bin_path(kind + '.dat')).read_bytes()
    names = set()
    for number, entry in fields(data):
        if number == 1:
            for field, value in fields(entry):
                if field == 1:
                    names.add(value.decode('ascii').lower()); break
    return sorted(names)
