"""Release trust policy. Replace at build time, never from an unsigned manifest.

Обновления публикуются в релизах GitHub: подписанный манифест beta.json лежит
в последнем ПК-релизе, MSI — рядом. GitHub отдаёт файлы через перенаправление
на свой CDN; разрешены только перечисленные хосты.
"""
MANIFEST_BASE = 'https://github.com/versadness/SadnessVPN/releases/latest/download'
ALLOWED_HOSTS = ('github.com',)
REDIRECT_HOSTS = ('release-assets.githubusercontent.com', 'objects.githubusercontent.com')
PUBLIC_KEY_BASE64 = 'XJxV/P4B3EoGcQwhaWKpb7hInXyEuk4WGzcaT5Cgsek='
PRODUCT_CODE = '{AF1CD0C5-8C28-5AE1-B63A-CE6BB1C196A8}'
