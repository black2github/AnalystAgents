# Happ + КриптоПро NGate одновременно

Скрипты для Windows: повседневный VPN **Happ** (режим TUN) и корпоративный VPN банка **КриптоПро NGate**
работают одновременно. Трафик к серверам банка идёт только через NGate. Если NGate упал или не подключён,
этот трафик блокируется, а не уходит через Happ. Всё остальное идёт через Happ по его правилам.

Настоящие адреса и имена серверов банка хранятся только в `config.psd1`. Этот файл исключён из git,
потому что репозиторий публичный. На другой ноутбук переносите его вручную или соберите заново по шагам ниже.

## Как это устроено

| Механизм | Что делает |
|---|---|
| Маршруты NGate (`/32`) | NGate прописывает их сам. Они точнее маршрутов Happ (`0.0.0.0/1`, `128.0.0.0/1`), поэтому трафик к банку идёт в туннель NGate |
| Маршрут к шлюзу NGate | Задача `NGateGatewayRoute` (от SYSTEM, при старте, входе и подключении к сети) ставит `GatewayPrefix` через текущий физический адаптер. Без этого сам туннель NGate пошёл бы через Happ |
| Правило брандмауэра | Блокирует исходящий трафик к `BankAddresses` через адаптер Happ. Это и есть гарантия: при любом сбое маршрутов соединение не устанавливается, но через Happ не идёт |
| `hosts` | Имена шлюза и ресурсов банка разрешаются без DNS. Адрес шлюза нужен до подъёма туннеля, а Happ TUN не пропускает DNS-запросы мимо себя |

Порядок запуска: **Happ, затем NGate**.

## Установка на новом ноутбуке

### 1. Настройки Happ

- Режим работы **TUN**, провайдер TUN **Happ TUN**. Не меняйте провайдер после установки: у другого провайдера
  будет другой адаптер, и правило брандмауэра перестанет защищать.
- Kill switch и блокировка трафика вне VPN, если есть, выключены. Иначе NGate не подключится.
- В правилах маршрутизации Happ домен банка и `geoip:RU` относятся к **Direct**. Это запасной уровень защиты.

### 2. Сбор настроек: `config.psd1`

Скопируйте `config.example.psd1` в `config.psd1` и заполните. Команды ниже выполняются в PowerShell.

**Адаптер Happ** (Happ подключён в TUN): его имя идёт в `TunAdapterName`.
```powershell
Get-NetAdapter | Format-Table Name, InterfaceDescription, Status
```

**Адреса банка** (Happ выключен, NGate подключён): маршруты через адаптер NGate (`CP-TAP-Windows Adapter`).
Адреса `/32` и подсеть VPN идут в `BankAddresses`.
```powershell
Get-NetRoute -AddressFamily IPv4 | Where-Object { (Get-NetAdapter -InterfaceIndex $_.ifIndex -ErrorAction SilentlyContinue).InterfaceDescription -like 'CP-TAP*' } | Format-Table DestinationPrefix, NextHop
```

**DNS банка**: адреса DNS-серверов на адаптере NGate. Их тоже добавьте в `BankAddresses`.
```powershell
Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object ServerAddresses | Format-Table InterfaceAlias, ServerAddresses
```

**Шлюз NGate**: имя видно в окне NGate (поле адреса). Его адреса идут в `HostsEntries`, сеть `/24` вокруг них —
в `GatewayPrefix`, а `/23`, накрывающая шлюз и соседнюю сеть ресурсов, — в `BankAddresses`, если ресурсы рядом.
```powershell
Resolve-DnsName <имя шлюза> -Type A
```

**Имена ресурсов**: откройте ресурсы банка, которыми пользуетесь, затем посмотрите кэш DNS.
Найденные имена с адресами добавьте в `HostsEntries`.
```powershell
Get-DnsClientCache | Where-Object Entry -like '*<домен банка>*' | Format-Table Entry, Data
```

### 3. Установка (PowerShell от администратора, Happ подключён в TUN)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <путь>\tools\ngate-route\install.ps1
```

Установщик копирует скрипт маршрута и `config.psd1` в `C:\Program Files\NGateRoute`, регистрирует задачу,
создаёт правило брандмауэра и пишет `hosts` с резервной копией в `hosts.bak`. Повторный запуск безопасен:
так применяются изменения в `config.psd1`.

### 4. Проверка

Защита работает: NGate выключен, Happ включён. Ожидается адаптер Happ и `False`.
```powershell
Test-NetConnection <адрес ресурса банка> -Port 443 -WarningAction SilentlyContinue | Select-Object InterfaceAlias, TcpTestSucceeded
```

Маршруты при обоих VPN: шлюз должен идти через Wi-Fi или Ethernet, адреса банка — через адаптер NGate.
```powershell
'<адрес шлюза>','<адрес ресурса>' | ForEach-Object { $r = Find-NetRoute -RemoteIPAddress $_ | Select-Object -Last 1; "$_ -> $($r.InterfaceAlias) via $($r.NextHop)" }
```

Журнал задачи маршрута:
```powershell
Get-Content 'C:\Program Files\NGateRoute\ngate-gw-route.log' -Tail 5
```

После перезагрузки NGate должен подключиться без ручных команд.

## Откат

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <путь>\tools\ngate-route\uninstall.ps1
```

Правило брандмауэра остаётся, пока не передан ключ `-RemoveFirewallRule`.

## Что выяснилось при настройке (не наступать снова)

- **«Исключённые маршруты» Happ TUN маршрутов Windows не создают.** Поэтому маршрут к шлюзу ставит своя задача.
- **Номера адаптеров (`ifIndex`) меняются после перезагрузки.** Маршрут, прописанный по номеру, однажды
  оказался на отключённом Bluetooth-адаптере. Скрипт выбирает адаптер по текущему маршруту по умолчанию.
- **NRPT (DNS банка через NGate) с Happ TUN не работает.** Happ режет DNS-запросы мимо своего адаптера при любом
  «Типе DNS» и провайдере TUN. Поэтому имена ресурсов прописываются в `hosts`.
- **`Set-Content` в PowerShell 5.1 обнуляет файл до записи.** Если `hosts` занят, он остаётся пустым.
  Пишем через `[IO.File]::WriteAllLines` с повторами и резервной копией.
- **Банк сменил адрес шлюза или ресурса**: NGate не подключается или ресурс не открывается, но через Happ ничего
  не уходит. Обновите `config.psd1` и запустите установщик заново.
- После подключения NGate ресурс может открываться не сразу, до 20 секунд: браузер повторяет попытки,
  которые до этого отклонял брандмауэр.
