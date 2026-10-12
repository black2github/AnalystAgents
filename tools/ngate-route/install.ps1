# Установка: маршрут к шлюзу NGate мимо TUN Happ (задача планировщика), правило брандмауэра
# «трафик к банку - никогда через Happ», имена ресурсов банка в hosts.
# Настройки - config.psd1 рядом со скриптом (образец: config.example.psd1, порядок заполнения: README.md).
# Запускать в PowerShell от имени администратора, при подключённом Happ (TUN). Повторный запуск безопасен.
$ErrorActionPreference = 'Stop'

$me = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Запустите PowerShell от имени администратора.'
}

$ConfigPath = Join-Path $PSScriptRoot 'config.psd1'
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Нет $ConfigPath. Скопируйте config.example.psd1 в config.psd1 и заполните (см. README.md)."
}
$cfg = Import-PowerShellDataFile -LiteralPath $ConfigPath

$InstallDir = Join-Path $env:ProgramFiles 'NGateRoute'
$TaskName   = 'NGateGatewayRoute'
$Tag        = 'NGateRoute'

# 1. Скрипт маршрута и настройки - в Program Files: задача работает от SYSTEM, менять их может только администратор.
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'ngate-gw-route.ps1'), $ConfigPath -Destination $InstallDir -Force
$RouteScript = Join-Path $InstallDir 'ngate-gw-route.ps1'
Write-Host "[1/5] Скрипт маршрута: $RouteScript"

# 2. Задача планировщика: при старте, при входе и при каждом подключении к сети (NetworkProfile 10000).
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RouteScript`""
$evtClass = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
$onNetwork = New-CimInstance -CimClass $evtClass -ClientOnly
$onNetwork.Enabled = $true
$onNetwork.Subscription = '<QueryList><Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational">' +
    '<Select Path="Microsoft-Windows-NetworkProfile/Operational">*[System[(EventID=10000)]]</Select></Query></QueryList>'
$triggers = @((New-ScheduledTaskTrigger -AtStartup), (New-ScheduledTaskTrigger -AtLogOn), $onNetwork)
$taskPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Principal $taskPrincipal `
    -Settings $settings -Description 'Маршрут к шлюзу NGate мимо TUN Happ' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "[2/5] Задача планировщика $TaskName зарегистрирована и запущена"

# 3. Брандмауэр: пакеты к банку, попавшие в адаптер Happ, отбрасываются (защита на случай падения NGate).
# Правило привязывается к адаптеру, поэтому создаётся только при подключённом Happ. Если Happ не подключён,
# существующее правило не трогаем - иначе установщик снял бы защиту.
if (Get-NetAdapter -Name $cfg.TunAdapterName -ErrorAction SilentlyContinue) {
    # Сначала новое правило, потом удаление старых: если создание упадёт, прежняя защита останется.
    $oldRules = @(Get-NetFirewallRule -DisplayName $cfg.FirewallRuleName -ErrorAction SilentlyContinue)
    New-NetFirewallRule -DisplayName $cfg.FirewallRuleName -Direction Outbound -Action Block `
        -InterfaceAlias $cfg.TunAdapterName -RemoteAddress $cfg.BankAddresses | Out-Null
    $oldRules | Remove-NetFirewallRule
    Write-Host "[3/5] Брандмауэр: '$($cfg.FirewallRuleName)' на адаптере $($cfg.TunAdapterName), адресов: $(@($cfg.BankAddresses).Count)"
} else {
    Write-Warning "[3/5] Адаптер $($cfg.TunAdapterName) не найден: подключите Happ в режиме TUN и запустите установщик снова. Правило брандмауэра НЕ обновлено."
}

# 4. Правила NRPT от ранних версий установщика не работают вместе с Happ TUN - убираем, если остались.
Get-DnsClientNrptRule | Where-Object Comment -eq $Tag | ForEach-Object { Remove-DnsClientNrptRule -Name $_.Name -Force }
Write-Host '[4/5] NRPT: правила NGateRoute убраны (не используются)'

# 5. hosts: наши строки пересобираются целиком, чтобы смена адреса не оставляла старых записей.
$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$kept = @(Get-Content -LiteralPath $hostsPath | Where-Object { $_ -notmatch "#\s*$Tag\s*$" })
$ours = @(foreach ($e in $cfg.HostsEntries) { foreach ($ip in $e.IPs) { "$ip`t$($e.Name)`t# $Tag" } })
# Резервная копия перед записью. WriteAllLines не очищает файл заранее (в отличие от Set-Content в PS 5.1):
# если hosts занят, он остаётся как был. Занят бывает кратко (антивирус, служба DNS) - пробуем до 10 раз.
if ((Get-Item -LiteralPath $hostsPath).Length -gt 0) {
    Copy-Item -LiteralPath $hostsPath -Destination (Join-Path $InstallDir 'hosts.bak') -Force
}
for ($i = 1; ; $i++) {
    try { [IO.File]::WriteAllLines($hostsPath, [string[]]($kept + $ours), [Text.Encoding]::ASCII); break }
    catch [IO.IOException] {
        if ($i -ge 10) { throw "hosts занят другим процессом, запись не удалась: $($_.Exception.Message)" }
        Start-Sleep -Milliseconds 700
    }
}
Clear-DnsClientCache
foreach ($e in $cfg.HostsEntries) { Write-Host "[5/5] hosts: $($e.Name) -> $($e.IPs -join ', ')" }

# Итог
Start-Sleep -Seconds 3
$direct = @($cfg.DirectPrefixes | Where-Object { $_ })
if ($direct.Count -eq 0) { $direct = @($cfg.GatewayPrefix | Where-Object { $_ }) }
Write-Host "`nМаршруты напрямую, мимо Happ:"
Get-NetRoute -DestinationPrefix $direct -ErrorAction SilentlyContinue |
    Format-Table DestinationPrefix, InterfaceAlias, NextHop, RouteMetric -AutoSize
Write-Host 'Журнал задачи:'
Get-Content -LiteralPath (Join-Path $InstallDir 'ngate-gw-route.log') -Tail 3 -ErrorAction SilentlyContinue
