# Диагностика: куда маршрутизируются корпоративные хосты, блокирует ли их правило брандмауэра и отвечают ли они.
# Только чтение, права администратора не нужны. Результат - текстовый файл в профиле пользователя.
# В файле будут адреса банка: в репозиторий его не класть.
#
# Пример: powershell -NoProfile -ExecutionPolicy Bypass -File diagnose.ps1 -Label happ-on -Domain bank -Hosts host1,host2 -Ports 443,8443
param(
    [string[]]$Hosts = @(),     # имена или адреса для явной проверки, через запятую
    [string]$Domain = '',       # дополнительно взять имена из кэша DNS по подстроке (например, часть домена банка)
    [string[]]$Ports = @('443'),# порты для проверки TCP-соединения, через запятую
    [string]$Label = 'diag'     # метка в имени файла: happ-off / happ-on
)
$ErrorActionPreference = 'Continue'
# При запуске через -File списки приходят одной строкой «a,b» - разбираем сами.
$Hosts = @($Hosts | ForEach-Object { $_ -split '[,;\s]+' } | Where-Object { $_ })
$Ports = @($Ports | ForEach-Object { $_ -split '[,;\s]+' } | Where-Object { $_ } | ForEach-Object { [int]$_ })
$OutFile = Join-Path $env:USERPROFILE ('ngate-diag-{0}-{1}.txt' -f $Label, (Get-Date -Format 'yyyyMMdd-HHmmss'))
$Lines = New-Object System.Collections.Generic.List[string]
function Out-Line([string]$s = '') { $Lines.Add($s); Write-Host $s }

function ConvertTo-UInt32([string]$ip) {
    $b = ([Net.IPAddress]::Parse($ip)).GetAddressBytes(); [Array]::Reverse($b); [BitConverter]::ToUInt32($b, 0)
}
# Адрес в сети: «a.b.c.d», «a.b.c.d/23» или «a.b.c.d/255.255.254.0» (так хранит брандмауэр).
function Test-InCidr([string]$ip, [string]$cidr) {
    $p = $cidr.Split('/')
    if (-not [Net.IPAddress]::TryParse($p[0], [ref]$null)) { return $false }
    if ($p.Count -gt 1 -and $p[1].Contains('.')) { $mask = ConvertTo-UInt32 $p[1] }
    else {
        $bits = 32; if ($p.Count -gt 1) { $bits = [int]$p[1] }
        $mask = [uint32](([uint64]4294967295 -shl (32 - $bits)) -band [uint64]4294967295)
    }
    ((ConvertTo-UInt32 $ip) -band $mask) -eq ((ConvertTo-UInt32 $p[0]) -band $mask)
}
function Test-Tcp([string]$ip, [int]$port, [int]$ms = 3000) {
    $c = New-Object Net.Sockets.TcpClient
    try {
        $t = $c.ConnectAsync($ip, $port)
        if ($t.Wait($ms)) { 'ok' } else { 'timeout' }
    } catch {
        $e = $_.Exception; while ($e.InnerException) { $e = $e.InnerException }
        # AccessDenied (10013) - соединение запретил брандмауэр.
        if ($e -is [Net.Sockets.SocketException]) { "err:$($e.SocketErrorCode)" } else { 'err' }
    } finally { $c.Dispose() }
}
function Get-RouteInfo([string]$ip) {
    $r = Find-NetRoute -RemoteIPAddress $ip -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($r) { '{0} via {1}' -f $r.InterfaceAlias, $r.NextHop } else { 'нет маршрута' }
}
function Resolve-A([string]$name, [string]$server) {
    try {
        $rq = @{ Name = $name; Type = 'A'; QuickTimeout = $true; ErrorAction = 'Stop' }
        if ($server) { $rq.Server = $server; $rq.DnsOnly = $true }
        $ips = @(Resolve-DnsName @rq | Where-Object { $_.Type -eq 'A' } | Select-Object -ExpandProperty IPAddress)
        if ($ips.Count) { $ips } else { @('нет A-записей') }
    } catch { @('ошибка: ' + ($_.Exception.Message -split "`n")[0].Trim()) }
}

# Настройки установки (имя адаптера Happ и правила брандмауэра), если config.psd1 рядом.
$TunName = 'happ-default-tun'; $RuleName = 'Bank: never via Happ'
$cfgPath = Join-Path $PSScriptRoot 'config.psd1'
if (Test-Path -LiteralPath $cfgPath) {
    $cfg = Import-PowerShellDataFile -LiteralPath $cfgPath
    $TunName = $cfg.TunAdapterName; $RuleName = $cfg.FirewallRuleName
}

Out-Line "Диагностика NGate/Happ: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), метка: $Label"
$tun = Get-NetAdapter -Name $TunName -ErrorAction SilentlyContinue
$ng = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object InterfaceDescription -like 'CP-TAP*' | Select-Object -First 1
Out-Line ("Happ ({0}): {1}" -f $TunName, $(if ($tun) { $tun.Status } else { 'нет адаптера' }))
Out-Line ("NGate ({0}): {1}" -f $(if ($ng) { $ng.Name } else { '-' }), $(if ($ng) { $ng.Status } else { 'нет адаптера' }))

$BankDns = @()
if ($ng -and $ng.Status -eq 'Up') {
    $BankDns = @((Get-DnsClientServerAddress -InterfaceIndex $ng.ifIndex -AddressFamily IPv4).ServerAddresses)
    Out-Line "DNS банка (адаптер NGate): $($BankDns -join ', ')"
    Out-Line 'Маршруты NGate:'
    Get-NetRoute -InterfaceIndex $ng.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.DestinationPrefix -notlike '224.*' -and $_.DestinationPrefix -ne '255.255.255.255/32' } |
        ForEach-Object { Out-Line ('  {0,-20} via {1}' -f $_.DestinationPrefix, $_.NextHop) }
}

$Blocked = @()
$rule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Select-Object -First 1
if ($rule) {
    $Blocked = @(($rule | Get-NetFirewallAddressFilter).RemoteAddress)
    Out-Line "Правило брандмауэра '$RuleName' (Enabled=$($rule.Enabled)): $($Blocked -join ', ')"
} else { Out-Line "Правило брандмауэра '$RuleName' не найдено" }

# Имена: явные + из кэша DNS (включая неудачные попытки разрешения).
$names = New-Object System.Collections.Generic.List[string]
foreach ($h in $Hosts) { if ($h -and -not $names.Contains($h)) { $names.Add($h) } }
if ($Domain) {
    Get-DnsClientCache -ErrorAction SilentlyContinue | Where-Object Entry -like "*$Domain*" |
        Select-Object -ExpandProperty Entry -Unique | ForEach-Object { if (-not $names.Contains($_)) { $names.Add($_) } }
}

Out-Line ''
Out-Line ('=== Хосты (порты: {0}) ===' -f ($Ports -join ', '))
foreach ($n in $names) {
    Out-Line ''
    Out-Line "[$n]"
    $isIp = [Net.IPAddress]::TryParse($n, [ref]$null)
    $ips = New-Object System.Collections.Generic.List[string]
    if ($isIp) { $ips.Add($n) } else {
        $sys = Resolve-A $n ''
        Out-Line ("  DNS системы:   {0}" -f ($sys -join ', '))
        if ($BankDns.Count) {
            $bank = Resolve-A $n $BankDns[0]
            Out-Line ("  DNS банка:     {0}" -f ($bank -join ', '))
        } else { $bank = @() }
        foreach ($ip in @($sys) + @($bank)) {
            if ([Net.IPAddress]::TryParse($ip, [ref]$null) -and -not $ips.Contains($ip)) { $ips.Add($ip) }
        }
    }
    foreach ($ip in $ips) {
        $inRule = @($Blocked | Where-Object { Test-InCidr $ip $_ }).Count -gt 0
        $tcp = @(foreach ($p in $Ports) { '{0}={1}' -f $p, (Test-Tcp $ip $p) }) -join ' '
        Out-Line ('  {0,-16} маршрут: {1,-45} в правиле: {2,-3} tcp: {3}' -f $ip, (Get-RouteInfo $ip), $(if ($inRule) { 'да' } else { 'нет' }), $tcp)
    }
}

# Зависшие соединения: SYN отправлен, ответа нет. Показывают, к каким адресам «подвисают» программы.
Out-Line ''
Out-Line '=== Зависшие TCP-соединения (SynSent) ==='
$syn = @(Get-NetTCPConnection -State SynSent -ErrorAction SilentlyContinue | Where-Object RemoteAddress -match '^\d+\.\d+\.\d+\.\d+$')
if ($syn.Count -eq 0) { Out-Line '  нет' }
foreach ($c in $syn) {
    $proc = (Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    $inRule = @($Blocked | Where-Object { Test-InCidr $c.RemoteAddress $_ }).Count -gt 0
    Out-Line ('  {0,-16}:{1,-5} {2,-20} маршрут: {3,-45} в правиле: {4}' -f $c.RemoteAddress, $c.RemotePort, $proc, (Get-RouteInfo $c.RemoteAddress), $(if ($inRule) { 'да' } else { 'нет' }))
}

[IO.File]::WriteAllLines($OutFile, [string[]]$Lines, (New-Object Text.UTF8Encoding $true))
Write-Host "`nСохранено: $OutFile"
