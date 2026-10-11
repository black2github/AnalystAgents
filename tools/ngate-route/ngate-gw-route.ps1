# Маршрут к шлюзу NGate через текущий физический адаптер, мимо TUN Happ.
# Запускается задачей планировщика NGateGatewayRoute от SYSTEM: при старте, при входе и при подключении к сети.
# Сеть шлюза берётся из config.psd1 рядом со скриптом (install.ps1 копирует его вместе со скриптом).
$ErrorActionPreference = 'Stop'
$LogFile = Join-Path $PSScriptRoot 'ngate-gw-route.log'

function Write-Log([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    # Журнал не растёт бесконечно: держим последние 500 строк.
    $all = @(Get-Content -LiteralPath $LogFile -Encoding UTF8)
    if ($all.Count -gt 500) { $all[-500..-1] | Set-Content -LiteralPath $LogFile -Encoding UTF8 }
}

function Get-PhysicalDefaultRoute {
    $phys = @(Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | Select-Object -ExpandProperty ifIndex)
    if ($phys.Count -eq 0) { return $null }
    Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $phys -contains $_.ifIndex -and $_.NextHop -ne '0.0.0.0' } |
        Sort-Object { $_.RouteMetric + (Get-NetIPInterface -InterfaceIndex $_.ifIndex -AddressFamily IPv4).InterfaceMetric } |
        Select-Object -First 1
}

try {
    $Prefix = (Import-PowerShellDataFile -LiteralPath (Join-Path $PSScriptRoot 'config.psd1')).GatewayPrefix

    # После подключения к сети шлюз по DHCP появляется не сразу: ждём до 60 секунд.
    $def = $null
    for ($i = 0; $i -lt 12 -and -not $def; $i++) {
        $def = Get-PhysicalDefaultRoute
        if (-not $def) { Start-Sleep -Seconds 5 }
    }
    if (-not $def) {
        Write-Log 'нет активного физического адаптера со шлюзом, маршрут не ставлю'
        exit 0
    }

    # Номера адаптеров и шлюз меняются (перезагрузка, другая сеть): убираем маршруты не туда.
    foreach ($r in @(Get-NetRoute -DestinationPrefix $Prefix -ErrorAction SilentlyContinue)) {
        if ($r.ifIndex -ne $def.ifIndex -or $r.NextHop -ne $def.NextHop) {
            $r | Remove-NetRoute -Confirm:$false
            Write-Log ('удалён устаревший маршрут: {0} через {1}' -f $r.InterfaceAlias, $r.NextHop)
        }
    }

    if (Get-NetRoute -DestinationPrefix $Prefix -InterfaceIndex $def.ifIndex -ErrorAction SilentlyContinue) {
        Write-Log ('маршрут на месте: {0} через {1} ({2})' -f $Prefix, $def.NextHop, $def.InterfaceAlias)
    } else {
        New-NetRoute -DestinationPrefix $Prefix -InterfaceIndex $def.ifIndex -NextHop $def.NextHop -RouteMetric 1 -PolicyStore ActiveStore | Out-Null
        Write-Log ('маршрут добавлен: {0} через {1} ({2})' -f $Prefix, $def.NextHop, $def.InterfaceAlias)
    }
} catch {
    Write-Log ('ошибка: {0}' -f $_.Exception.Message)
    exit 1
}
