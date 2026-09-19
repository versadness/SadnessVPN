<#
.SYNOPSIS
    Полный цикл выпуска Sadness VPN одной командой.

.DESCRIPTION
    Обёртка над существующими инструментами, ничего не подменяет:
      build_candidate.py -> test_installer_roundtrip.py -> micro_test.py
      -> publish_release.py -> verify_published_release.py

    Публикация на VPS требует явного -Publish. Без него скрипт только собирает
    и проверяет кандидата локально, как того требует порядок выпуска.

    Пароль SSH не принимается параметром и нигде не сохраняется: его спрашивает
    сам publish_release.py через getpass в момент подключения.

.EXAMPLE
    .\tools\release.ps1 -Notes installer\release-notes-2.0.25.json
    Собрать и проверить кандидата, не публикуя.

.EXAMPLE
    .\tools\release.ps1 -Notes installer\release-notes-2.0.25.json -ApproveManual -Publish
    Опубликовать после того, как ручной тест владельцем реально проведён.
#>
[CmdletBinding()]
param(
    # Базы для прямых MSP-патчей. Сверяются с наличием локальных MSI.
    # По умолчанию пусто: от MSP отказались, полный MSI ставится поверх сам.
    # Указывайте -Base только если патч нужен осознанно.
    [string[]]$Base = @(),

    # JSON со списком изменений, например installer\release-notes-2.0.26.json
    [string]$Notes,

    # Мажорный апгрейд: собрать только полный MSI, без патчей и публикации.
    # Нужен, когда сменился ProductCode — прямые MSP тогда невозможны.
    [switch]$MsiOnly,

    # Владелец реально проверил запуск, трей, окно, VPN и маршрутизацию.
    [switch]$ApproveManual,

    # Владелец разрешил публикацию без ручного теста. В отчёте это фиксируется.
    [switch]$TechnicalOnly,

    # Заливать на VPS. Без него публикации не будет.
    [switch]$Publish,

    # Пропустить установочные тесты. Внимание: они меняют установленную версию.
    [switch]$SkipInstallTests,

    # Продолжить выпуск на уже собранном кандидате: шаг сборки пропускается,
    # проверка «кандидат уже существует» тоже. Нужен, когда сборка прошла,
    # а упал один из тестов ниже — пересобирать сорок минут незачем.
    [switch]$Resume,

    # Куда сложить готовые .msp после сборки. Пустая строка — не копировать.
    [string]$CopyTo = [Environment]::GetFolderPath('Desktop'),

    [string]$Config = 'installer\vps-config.production.json',
    [string]$SigningKey = "$env:LOCALAPPDATA\SadnessVPN-ReleaseKeys\publisher-ed25519.pem"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root 'venv311\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw "Не найден интерпретатор проекта: $Python" }

# Берём последнюю строку: любое предупреждение Python не должно попасть в номер версии.
$versionOutput = & $Python -c "import sys; sys.path.insert(0,'.'); from engine.app_meta import APP_VERSION; print(APP_VERSION)"
if ($LASTEXITCODE -ne 0) { throw 'Не удалось выполнить engine/app_meta.py' }
$Version = ($versionOutput | Select-Object -Last 1)
if (-not $Version) { throw 'Не удалось прочитать APP_VERSION из engine/app_meta.py' }
$Version = $Version.ToString().Trim()

$LogDir = Join-Path $Root "build\release-$Version"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ('release-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')

function Write-Step {
    param([string]$Text)
    $line = "`n=== $Text ==="
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $Log -Value $line -Encoding utf8
}

function Invoke-Step {
    # Выполняет шаг, дублируя вывод на экран и в общий лог.
    param([string]$Title, [string[]]$Arguments)
    Write-Step $Title
    Add-Content -Path $Log -Value ("> " + $Python + ' ' + ($Arguments -join ' ')) -Encoding utf8
    # stderr нативной программы при ErrorActionPreference='Stop' превращается
    # в NativeCommandError и не доходит до лога. Поэтому на время шага
    # переключаемся на Continue: тогда трассировка Python попадает в файл.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Python @Arguments 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $Log -Append
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Шаг «$Title» завершился с кодом $LASTEXITCODE. Подробности: $Log"
    }
}

Write-Step "Выпуск Sadness VPN $Version"
Add-Content -Path $Log -Value "Базы: $($Base -join ', ')" -Encoding utf8

# --- предполётные проверки ---------------------------------------------------
# Дешевле упасть здесь, чем через сорок минут сборки.

if (-not $MsiOnly) {
    if (-not $Notes) { throw 'Укажите -Notes, либо соберите только установщик ключом -MsiOnly.' }
    if (-not (Test-Path $Notes)) { throw "Не найден файл с описанием изменений: $Notes" }
}

foreach ($b in ($(if ($MsiOnly) { @() } else { $Base }))) {
    $msi = Join-Path $Root "dist\SadnessVPN-$b-Setup-x64.msi"
    if (-not (Test-Path $msi)) {
        throw "Нет локального MSI базы $b ($msi). Без него прямой патч с этой версии не собрать."
    }
}

$Candidate = Join-Path $Root "dist\candidate\$Version"
if (-not $MsiOnly -and -not $Resume -and (Test-Path $Candidate)) {
    throw "Кандидат $Version уже существует: $Candidate. Проверенные файлы не пересобираются — поднимите версию или уберите каталог вручную."
}

if ($Publish) {
    if (-not (Test-Path $Config)) {
        throw "Нет конфигурации VPS: $Config. Скопируйте installer\vps-config.production.example.json и заполните."
    }
    if (-not (Test-Path $SigningKey)) {
        throw "Нет закрытого ключа подписи: $SigningKey"
    }
}

# --- сборка ------------------------------------------------------------------

$buildArgs = @('tools/build_candidate.py')
if ($MsiOnly) {
    $buildArgs += '--msi-only'
} else {
    foreach ($b in $Base) { $buildArgs += @('--base', $b) }
    $buildArgs += @('--notes', $Notes)
}
if ($Resume) {
    if (-not (Test-Path $Candidate)) { throw "Нечего продолжать: нет кандидата $Candidate" }
    Write-Step "Сборка пропущена: продолжаем на готовом кандидате $Version"
} else {
    Invoke-Step "Сборка $(if ($MsiOnly) { 'установщика' } else { 'кандидата' }) $Version" $buildArgs
}

if ($MsiOnly) {
    $msi = Join-Path $Root "dist\SadnessVPN-$Version-Setup-x64.msi"
    if (-not (Test-Path $msi)) { throw "Установщик не найден: $msi" }
    if ($CopyTo) {
        Copy-Item $msi -Destination $CopyTo -Force
        Write-Step "Установщик скопирован на рабочий стол"
    }
    Write-Step "Готово: $Version"
    '{0,10:N1} МиБ  {1}' -f ((Get-Item $msi).Length / 1MB), (Split-Path $msi -Leaf)
    Write-Host 'Патчи не собирались: сменился ProductCode, это мажорный апгрейд.' -ForegroundColor Yellow
    Write-Host 'Установка: msiexec /i "<путь к msi>"  (старая версия будет удалена автоматически)' -ForegroundColor Cyan
    return
}

# --- проверка патчей ---------------------------------------------------------
# msiexec строго по одному за раз: параллельные установки Windows Installer
# конфликтуют между собой и дают ложные отказы.

if ($Base.Count -eq 0) {
    Write-Step 'Патчи не собирались: MSP отключены, обновление идёт полным MSI'
} elseif ($SkipInstallTests) {
    Write-Step 'Установочные тесты пропущены по ключу -SkipInstallTests'
} else {
    Write-Host "`nВНИМАНИЕ: установочные тесты ставят и откатывают пакеты и могут изменить установленную у вас версию." -ForegroundColor Yellow
    foreach ($b in $Base) {
        Invoke-Step "Патч из образа $b -> $Version" @('tools/test_patch_admin.py', '--base', $b, '--new', $Version)
    }
    foreach ($b in $Base) {
        Invoke-Step "Реальная установка и откат $b -> $Version" @('tools/test_installer_roundtrip.py', '--base', $b, '--new', $Version)
    }
}

# --- сводный отчёт -----------------------------------------------------------

$microArgs = @('tools/micro_test.py', '--candidate', $Candidate)
if ($ApproveManual) { $microArgs += '--approve-manual' }
if ($TechnicalOnly) { $microArgs += '--technical-only-authorized' }
Invoke-Step 'Сводный отчёт проверок' $microArgs

# Готовые файлы отдаём сразу, даже если проверки ниже что-то не подтвердят.
# Патчи и полный установщик раскладываются отдельно: первое уходит на сервер
# обновлений, второе — в релиз на GitHub.
if ($CopyTo) {
    # Имя не должно отличаться от $Root только регистром: PowerShell
    # переменные по регистру не различает, и $Root (корень проекта)
    # затирался — полный MSI после этого не находился и молча не копировался.
    $outRoot = Join-Path $CopyTo "SadnessVPN-$Version"
    $patchDir = Join-Path $outRoot 'patches-for-server'
    $msiDir = Join-Path $outRoot 'installer-for-github'
    New-Item -ItemType Directory -Force -Path $patchDir, $msiDir | Out-Null

    # Без -Base патчей нет: подстановка по маске при ErrorActionPreference='Stop'
    # на пустом совпадении бросает исключение, поэтому перечисляем явно.
    $msp = @(Get-ChildItem -Path $Candidate -Filter '*.msp' -ErrorAction SilentlyContinue)
    if ($msp.Count -gt 0) { Copy-Item $msp.FullName -Destination $patchDir -Force }
    Copy-Item (Join-Path $Candidate 'update.json') -Destination $patchDir -Force
    Copy-Item (Join-Path $Candidate 'files.sha256.json') -Destination $patchDir -Force

    $msi = Join-Path $Root "dist\SadnessVPN-$Version-Setup-x64.msi"
    if (-not (Test-Path $msi)) { throw "Установщик не найден: $msi" }
    Copy-Item $msi -Destination $msiDir -Force

    # Описание собирается из тех же заметок, что уходят в манифест и в
    # историю версий внутри приложения — расхождений между ними не будет.
    $notesData = Get-Content $Notes -Raw -Encoding utf8 | ConvertFrom-Json
    $doc = [System.Collections.Generic.List[string]]::new()
    $doc.Add("# Sadness VPN $Version"); $doc.Add('')
    $doc.Add('## Что нового'); $doc.Add('')
    foreach ($note in $notesData) { $doc.Add("- $note") }
    $doc.Add(''); $doc.Add('## Установка'); $doc.Add('')
    $doc.Add("Обновление до $Version приходит в приложении автоматически: «Настройки» → «Обновления».")
    $doc.Add('Для чистой установки скачайте MSI и запустите его двойным кликом — предыдущая версия удалится сама, подписки, серверы и настройки сохранятся.')
    $doc.Add(''); $doc.Add('Требуется Windows 10 версии 2004 или новее / Windows 11, x64.')
    $doc.Add(''); $doc.Add('## Файлы'); $doc.Add('')
    $doc.Add('| Файл | Размер | SHA256 |'); $doc.Add('|---|---|---|')
    foreach ($f in @(Get-ChildItem $msiDir -Filter *.msi) + @(Get-ChildItem $patchDir -Filter *.msp | Sort-Object Name)) {
        $hash = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower()
        $row = '| `{0}` | {1:N1} МиБ | `{2}` |' -f $f.Name, ($f.Length / 1MB), $hash
        $doc.Add($row)
    }
    $doc.Add(''); $doc.Add('Проверить контрольную сумму:'); $doc.Add(''); $doc.Add('```')
    $doc.Add('Get-FileHash .\<файл> -Algorithm SHA256'); $doc.Add('```')
    Set-Content -Path (Join-Path $outRoot 'RELEASE-NOTES.md') -Value $doc -Encoding utf8

    Write-Step "Файлы разложены: $outRoot"
    Write-Host 'patches-for-server — на сервер обновлений:' -ForegroundColor Cyan
    if ($msp.Count -eq 0) {
        Write-Host '  update.json и files.sha256.json (MSP не собирались)'
    } else {
        Get-ChildItem $patchDir -Filter *.msp | ForEach-Object {
            '{0,10:N1} МиБ  {1}' -f ($_.Length / 1MB), $_.Name
        }
    }
    Write-Host 'RELEASE-NOTES.md — описание релиза' -ForegroundColor Cyan
    Write-Host 'installer-for-github — в релиз на GitHub:' -ForegroundColor Cyan
    Get-ChildItem $msiDir -Filter *.msi | ForEach-Object {
        '{0,10:N1} МиБ  {1}' -f ($_.Length / 1MB), $_.Name
        'SHA256 ' + (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    }
}

$report = Get-Content (Join-Path $Candidate 'test-report.json') -Raw | ConvertFrom-Json
if (-not $report.ready) {
    Write-Host "`nКандидат собран, но НЕ готов к публикации." -ForegroundColor Yellow
    Write-Host "Отчёт: $Candidate\test-report.json" -ForegroundColor Yellow
    if (-not ($ApproveManual -or $TechnicalOnly)) {
        Write-Host 'Не хватает подтверждения владельца: проведите короткий тест и перезапустите с -ApproveManual.' -ForegroundColor Yellow
    }
    if ($Publish) { throw 'Публикация отменена: проверки не пройдены.' }
    return
}

if (-not $Publish) {
    Write-Step 'Готово. Публикация не запрашивалась'
    Write-Host "Кандидат: $Candidate" -ForegroundColor Green
    Write-Host 'Для публикации перезапустите с ключом -Publish.' -ForegroundColor Green
    return
}

# --- публикация --------------------------------------------------------------
# publish_release.py сам заливает во временный incoming-каталог, проверяет
# подпись и файлы на сервере, атомарно переключает beta.json и вызывает
# серверный хелпер, который удаляет патчи, на которые больше никто не ссылается.

Write-Step 'Публикация на VPS'
Write-Host 'Пароль SSH запросит publish_release.py. Он нигде не сохраняется.' -ForegroundColor Cyan
Invoke-Step 'Загрузка и активация' @(
    'tools/publish_release.py',
    '--candidate', $Candidate,
    '--config', $Config,
    '--signing-key', $SigningKey,
    '--publish'
)

Invoke-Step 'Внешняя проверка по HTTPS' @('tools/verify_published_release.py', '--version', $Version)

Write-Step "Релиз $Version опубликован и проверен"
Write-Host "Полный лог: $Log" -ForegroundColor Green
