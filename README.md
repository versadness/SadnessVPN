# Sadness VPN · BETA

> [!WARNING]
> **Приложение находится в бета-тестировании и может работать нестабильно.**
> Возможны ошибки запуска, подключения и маршрутизации. Не используйте Sadness VPN как единственный VPN для важных подключений.
> Нашли ошибку — [сообщите в Issues](https://github.com/versadness/SadnessVPN/issues/new).

![Status: Beta](https://img.shields.io/badge/status-BETA-orange)
![Windows x64](https://img.shields.io/badge/platform-Windows_10%2F11_x64-0078D4)
![Linux x86_64](https://img.shields.io/badge/platform-Linux_x86__64-FCC624)
![Release: 3.4.0 Beta](https://img.shields.io/badge/release-3.4.0_Beta-8b5cf6)

VPN-клиент для Windows и Linux с подписками, TUN, маршрутизацией отдельных приложений через разные серверы и стеклянным интерфейсом Electron.

## Скачать 3.4.0 Beta

### [Скачать полный Setup.exe для Windows x64 · около 167 МиБ](https://github.com/versadness/SadnessVPN/releases/download/v3.4.0-beta/SadnessVPN-3.4.0-Setup-x64.exe)

### Linux x86_64 (Beta)

| Система | Скачать | Установка |
|---|---|---|
| Ubuntu / Debian / Mint | [`.deb` · 103 МиБ](https://github.com/versadness/SadnessVPN/releases/download/v3.4.0-beta/SadnessVPN-3.4.0-linux-amd64.deb) | `sudo apt install ./SadnessVPN-3.4.0-linux-amd64.deb` |
| Fedora | [`.rpm` · 103 МиБ](https://github.com/versadness/SadnessVPN/releases/download/v3.4.0-beta/SadnessVPN-3.4.0-linux-x86_64.rpm) | `sudo dnf install ./SadnessVPN-3.4.0-linux-x86_64.rpm` |
| Arch / Manjaro | [`.pacman` · 103 МиБ](https://github.com/versadness/SadnessVPN/releases/download/v3.4.0-beta/SadnessVPN-3.4.0-linux-x64.pacman) | `sudo pacman -U SadnessVPN-3.4.0-linux-x64.pacman` |
| Bazzite и любой другой | [`AppImage` · 145 МиБ](https://github.com/versadness/SadnessVPN/releases/download/v3.4.0-beta/SadnessVPN-3.4.0-linux-x86_64.AppImage) | `chmod +x` и запустить |

[Описание версии 3.4.0](https://github.com/versadness/SadnessVPN/releases/tag/v3.4.0-beta) · [Все версии](https://github.com/versadness/SadnessVPN/releases)

Файл **`SadnessVPN-3.4.0-Setup-x64.exe`** — однофайловый установщик с иконкой приложения и полным MSI внутри. Python, Electron и VPN-ядра уже включены; WebView2 отдельно скачивать не требуется. Пакеты Linux тоже самодостаточны.

Архивы **Source code** на странице релиза — снимки репозитория дистрибутивов, а не установщики клиента.

## Что нового в 3.4.0

- **Linux (Beta):** Ubuntu, Fedora, Arch и Bazzite — AppImage, `.deb`, `.rpm` и pacman. Подписки, TUN, правила, смена сервера на лету и резерв работают как в Windows.
- **Пароль администратора на Linux — один раз:** пакеты выдают права ядру VPN при установке, AppImage — при первом подключении. Само приложение работает от обычного пользователя.
- На Linux пока нет Zapret, AmneziaWG и встроенного автообновления.
- Windows и Linux: неразрешимый адрес запасного сервера больше не срывает подключение.

Подробности перечислены на [странице релиза 3.4.0](https://github.com/versadness/SadnessVPN/releases/tag/v3.4.0-beta).

## Изменения предыдущих версий

### 3.3.0

- **Смена сервера на лету**: пока VPN работает, выберите другой сервер — трафик пойдёт через него без переподключения.
- **Автоматическая замена сервера**: если сервер перестал отвечать, трафик переходит на запасной из той же подписки и на том же транспорте, а потом возвращается.

[Подробнее о 3.3.0](https://github.com/versadness/SadnessVPN/releases/tag/v3.3.0-beta)

### 3.2.1

- Журнал подключения содержит только последнюю сессию; системный журнал хранится отдельно.

[Подробнее о 3.2.1](https://github.com/versadness/SadnessVPN/releases/tag/v3.2.1-beta)

### 3.2.0

- Прозрачное окно со своим фоном: картинка лежит поверх рабочего стола полупрозрачным чётким слоем.
- Матовое стекло панелей поверх своего фона.

[Подробнее о 3.2.0](https://github.com/versadness/SadnessVPN/releases/tag/v3.2.0-beta)

### 3.1.8–3.1.9

- Пользовательский фон снова виден в приложении, настройки стекла действуют на него.
- Понятные уведомления об обновлении подписок: статус на карточке и итог «Обновить все».

[Подробнее о 3.1.9](https://github.com/versadness/SadnessVPN/releases/tag/v3.1.9-beta) · [о 3.1.8](https://github.com/versadness/SadnessVPN/releases/tag/v3.1.8-beta)

### 3.1.7

- Подписки автоматически обновляются при каждом запуске приложения; автообновление можно выключить в «Настройках».

[Подробнее о 3.1.7](https://github.com/versadness/SadnessVPN/releases/tag/v3.1.7-beta)

### 3.1.6

- Раздел «Telegram» для Telegram WS Proxy в боковой панели.
- WireGuard-конфиги добавляются файлами `.conf`, название берётся из имени файла.
- Правила маршрутизации работают с обычным WireGuard и больше не блокируют подключение.
- Исправлены обрывы сайтов (`ERR_CONNECTION_CLOSED`) в браузерах со встроенным DNS.

[Подробнее о 3.1.6](https://github.com/versadness/SadnessVPN/releases/tag/v3.1.6-beta)

### 3.1.5

- Telegram WS Proxy — локальный MTProto-прокси для Telegram Desktop со своим портом и ключом.

[Подробнее о 3.1.5](https://github.com/versadness/SadnessVPN/releases/tag/v3.1.5-beta)

### 3.1.4

- Новый главный экран: карточка сервера со страной, флагом, протоколом и задержкой, спидометр текущей скорости.
- Подключение — широкий ползунок: перетащить, нажать или включить с клавиатуры.
- Под ползунком — отдача, время сессии, трафик за сегодня и внешний IP по запросу.

[Подробнее о 3.1.4](https://github.com/versadness/SadnessVPN/releases/tag/v3.1.4-beta)

### 3.1.3

- Исправлено подключение к обычному WireGuard: раньше ядро запускалось без туннеля.
- Автообновление больше не откатывает новую версию после установки.
- Автозапуск Windows снова открывает приложение со значком в трее.
- DNS обычных пресетов идёт через туннель, IPv6 больше не обходит VPN.
- ICMP-пинг работает на русской Windows, HTTP-пинг меряет задержку через каждый сервер.
- Вошли изменения 3.0.10–3.0.12: единственное ядро Mihomo, VMess, проверка сервера настоящим запросом.

[Подробнее о 3.1.3](https://github.com/versadness/SadnessVPN/releases/tag/v3.1.3-beta)

### 3.0.9

- Маршруты на исчезнувший из подписки сервер безопасно переводятся на основной VPN, а не приводят к безымянной ошибке подключения.
- Ошибки пользовательской конфигурации возвращают понятную причину вместо HTTP 500.
- Восстановлено копирование журнала и локального ID в буфер обмена.

[Подробнее о 3.0.9](https://github.com/versadness/SadnessVPN/releases/tag/v3.0.9-beta)

### 3.0.8

- Маршрутизация сокращена до двух вкладок: **«Приложения и серверы»** и **«Готовые наборы»**.
- Режимы **«Весь компьютер»**, **«Только выбранные»** и **«Кроме выбранных»** перенесены к списку правил.
- Правила приложений, доменов, GeoSite, GeoIP и IP-CIDR объединены в один список с назначением конкретного сервера.
- Добавлены семь готовых тематических наборов правил.

[Подробнее о 3.0.8](https://github.com/versadness/SadnessVPN/releases/tag/v3.0.8-beta)

### 3.0.7

- Повторный запуск открывает уже работающее или свёрнутое в трей окно без второго Electron и лишнего запроса прав.
- Снижено потребление CPU/GPU скрытым окном.
- Исправлены полосы прокрутки без системных стрелок.
- Удалены остатки неработавшей фоновой анимации.

[Подробнее о 3.0.7](https://github.com/versadness/SadnessVPN/releases/tag/v3.0.7-beta)

### 3.0.6

- Исправлены XHTTP-ссылки со служебными параметрами `scMaxConcurrentPosts`, `scMaxBufferedPosts`, `scStreamUpServerSecs`, `noSSEHeader` и `xmux.cMaxLifetimeMs`.
- Добавлена передача ECH из Hysteria 2 в Mihomo.
- Пакет уменьшен за счёт удаления сборок `koffi` для других платформ и лишних локализаций Chromium.
- Обновление удаляет компоненты, которые больше не входят в приложение.
- Улучшено штатное завершение бэкенда и ограничены разрешения окна.

[Подробнее о 3.0.6](https://github.com/versadness/SadnessVPN/releases/tag/v3.0.6-beta)

### 3.0.5

- XHTTP переведён на Mihomo, устранена проблема серверов с адресом, отличающимся от SNI.
- Xray удалён из пакета.
- Добавлен динамический порт Clash API и диагностика туннеля без передачи данных.
- Добавлен Setup.exe с иконкой приложения и проверкой встроенного MSI.

[Подробнее о 3.0.5](https://github.com/versadness/SadnessVPN/releases/tag/v3.0.5-beta)

## Возможности

- Раздельные группы серверов и подписок.
- VLESS, VMess, XHTTP, TLS/Reality, Shadowsocks, Trojan, Hysteria 2, WireGuard и AmneziaWG — в пределах возможностей сервера и ядра.
- Mihomo — единственное ядро для прокси-протоколов, TUN и WireGuard; AmneziaWG работает через собственную службу.
- TUN и локальные SOCKS5/HTTP-порты.
- Маршрутизация по приложениям, доменам, GeoSite, GeoIP и IP-CIDR.
- Одновременное назначение разных серверов разным приложениям.
- Windows 10/11 x64 и Linux x86_64 (Ubuntu, Fedora, Arch, Bazzite).
- AI-DNS, Zapret (Windows), статистика, журнал и встроенная проверка обновлений.
- Стеклянный интерфейс Electron, прозрачность и выбор акцентного цвета.

## Установка и обновление

### Windows

1. Используйте Windows 10/11 x64.
2. Отключите VPN и полностью закройте клиент, включая значок в трее.
3. Скачайте `SadnessVPN-3.4.0-Setup-x64.exe` только из Assets официального релиза.
4. Запустите файл и подтвердите системный запрос, если доверяете источнику.
5. После установки запускайте Sadness VPN через созданный ярлык.

Профиль пользователя хранится отдельно:

```text
%LOCALAPPDATA%\SadnessVPN\data
```

### Linux

1. Скачайте пакет для своей системы из таблицы выше и установите его командой из таблицы. Пароль спросит пакетный менеджер — это и есть единственный раз: дальше VPN включается без пароля.
2. С AppImage: сделайте файл исполняемым (`chmod +x`) и запустите. При первом подключении система один раз спросит пароль администратора, чтобы выдать права ядру VPN.
3. Новую версию ставьте так же — свежим пакетом или AppImage; встроенное автообновление на Linux пока не работает.

Профиль пользователя: `~/.local/share/SadnessVPN`. На Linux пока недоступны Zapret и AmneziaWG.

Подписки, правила и настройки не входят в публичный установщик.

## Проверка загрузки

| Файл | Размер, байт | SHA256 |
|---|---|---|
| `SadnessVPN-3.4.0-Setup-x64.exe` (версия **3.4.0.0**) | 174 659 095 | `666481224bd4231bd7a90728e74fe9986ccdd34cd8723e730a4e1d722717240b` |
| `SadnessVPN-3.4.0-linux-x86_64.AppImage` | 152 190 850 | `0128fda44e1747c3d6c6f53621a19d31a68bb871540df22ac375a7d2d5b6990b` |
| `SadnessVPN-3.4.0-linux-amd64.deb` | 108 121 410 | `db6c2e146a872650ff0e2b1e70e30b0e62a99cba2a521735718e5420eb86f11b` |
| `SadnessVPN-3.4.0-linux-x86_64.rpm` | 107 984 165 | `9351b98deebd4b1da32bcb5dcdad3ce3adf1c8217dfcf1195f2fd45f282c66dc` |
| `SadnessVPN-3.4.0-linux-x64.pacman` | 108 146 748 | `ef006d9ba39bd31ee24cb58a28783bdd96b191a1d292f1e0d18c17c4a46fd1fa` |

Проверка в PowerShell:

```powershell
Get-FileHash -LiteralPath '.\SadnessVPN-3.4.0-Setup-x64.exe' -Algorithm SHA256
```

На Linux: `sha256sum <файл>`.

Совпадение SHA256 подтверждает соответствие опубликованному файлу, но не заменяет цифровую подпись. Установщик пока не подписан сертификатом издателя, поэтому SmartScreen может показать предупреждение «Неизвестный издатель».

## Если возникла ошибка

[Создать Issue](https://github.com/versadness/SadnessVPN/issues/new)

Укажите версию Windows или дистрибутив Linux, версию Sadness VPN, шаги воспроизведения, ожидаемый результат и приложите скриншот. При проблемах подключения укажите протокол и транспорт сервера.

Журналы:

```text
%LOCALAPPDATA%\SadnessVPN\data\diagnostics
```

На Linux: `~/.local/share/SadnessVPN/data/diagnostics`.

**Issues публичные. Не публикуйте ссылки подписок, UUID, приватные ключи, пароли, HWID и полные конфиги.** Перед отправкой журнала удалите личные данные и адреса серверов.

Не отключайте Defender и не добавляйте исключения ради запуска. Если защита сообщает об угрозе, прекратите запуск и приложите название обнаружения к Issue.

## О репозитории

Это репозиторий бета-дистрибутивов, документации и сообщений об ошибках. Публикация установщика не означает публикацию исходного кода клиента.

Предыдущие версии доступны в [Releases](https://github.com/versadness/SadnessVPN/releases). Инструкции старых релизов относятся только к соответствующим версиям.
