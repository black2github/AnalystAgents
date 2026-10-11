# Откат install.ps1: задача, скрипт, правила NRPT, строки hosts.
# Правило брандмауэра снимается только с ключом -RemoveFirewallRule: без него трафик к банку
# при упавшем NGate снова может уйти через Happ.
# Запускать в PowerShell от имени администратора.
param([switch]$RemoveFirewallRule)
$ErrorActionPreference = 'Stop'
$Tag = 'NGateRoute'

Unregister-ScheduledTask -TaskName 'NGateGatewayRoute' -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $env:ProgramFiles 'NGateRoute') -Recurse -Force -ErrorAction SilentlyContinue
Get-DnsClientNrptRule | Where-Object Comment -eq $Tag | ForEach-Object { Remove-DnsClientNrptRule -Name $_.Name -Force }

$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$kept = @(Get-Content -LiteralPath $hostsPath | Where-Object { $_ -notmatch "#\s*$Tag\s*$" })
Copy-Item -LiteralPath $hostsPath -Destination (Join-Path $env:TEMP 'hosts.before-ngateroute-uninstall.bak') -Force
for ($i = 1; ; $i++) {
    try { [IO.File]::WriteAllLines($hostsPath, [string[]]$kept, [Text.Encoding]::ASCII); break }
    catch [IO.IOException] {
        if ($i -ge 10) { throw "hosts занят другим процессом, запись не удалась: $($_.Exception.Message)" }
        Start-Sleep -Milliseconds 700
    }
}
Clear-DnsClientCache

if ($RemoveFirewallRule) {
    $ruleName = 'Bank: never via Happ'
    $configPath = Join-Path $PSScriptRoot 'config.psd1'
    if (Test-Path -LiteralPath $configPath) { $ruleName = (Import-PowerShellDataFile -LiteralPath $configPath).FirewallRuleName }
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Host "Правило брандмауэра '$ruleName' снято."
}

Write-Host 'Готово. Маршрут к шлюзу NGate (если есть) исчезнет после перезагрузки.'
