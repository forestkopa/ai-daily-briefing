# ==============================================================
#  一条命令定位 daily.forestkopa.top 502 的原因
#  在【跑 cloudflared 隧道的那台机器】上，用管理员 PowerShell 运行
#
#  本脚本【只读】，不做任何修改。把全部输出截图发我即可。
# ==============================================================

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Line($t) { Write-Host ""; Write-Host ("---- " + $t + " ----") -ForegroundColor Cyan }

Write-Host "=============================================================="
Write-Host "  daily.forestkopa.top 502 排障（只读）"
Write-Host "=============================================================="
Write-Host ("  主机名 : " + $env:COMPUTERNAME)
Write-Host ("  时间   : " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))

# ---------------------------------------------------------- 1
Line "1. 本机 5190 有没有服务在听（最关键的判断）"
$listen = Get-NetTCPConnection -LocalPort 5190 -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    $ownerPid = $listen[0].OwningProcess
    $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
    Write-Host ("  [有] 端口 5190 正在监听") -ForegroundColor Green
    Write-Host ("       进程: " + $proc.ProcessName + "  (PID " + $ownerPid + ")")
    Write-Host ("       路径: " + $proc.Path)
} else {
    Write-Host "  [无] 端口 5190 没有任何进程在监听" -ForegroundColor Red
    Write-Host "       => 这就是 502 的直接原因：回源目标不存在。" -ForegroundColor Yellow
    Write-Host "       => 先把 daily 服务部署起来，再回来看域名。" -ForegroundColor Yellow
}

# ---------------------------------------------------------- 2
Line "2. 本机自测（HTTP 与 HTTPS 各试一次，对比差异）"
foreach ($u in @('http://127.0.0.1:5190/healthz', 'https://127.0.0.1:5190/healthz')) {
    try {
        $r = Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 6
        Write-Host ("  [OK]   " + $u + "  -> HTTP " + $r.StatusCode) -ForegroundColor Green
    } catch {
        $msg = $_.Exception.Message
        if ($msg.Length -gt 90) { $msg = $msg.Substring(0, 90) + '...' }
        Write-Host ("  [FAIL] " + $u + "  -> " + $msg) -ForegroundColor Red
    }
}

# ---------------------------------------------------------- 3
Line "3. cloudflared 服务与启动参数"
$svc = Get-Service | Where-Object { $_.Name -like '*cloudflared*' -or $_.DisplayName -like '*cloudflared*' } | Select-Object -First 1
if ($svc) {
    Write-Host ("  [有] " + $svc.Name + "  " + $svc.Status)
    $pname = (Get-CimInstance Win32_Service -Filter "Name='$($svc.Name)'").PathName
    Write-Host ("       启动命令: " + $pname)
    if ($pname -match 'tunnel\s+run') {
        Write-Host "       => 命名隧道（可以配固定域名）" -ForegroundColor Green
    } elseif ($pname -match '--url') {
        Write-Host "       => Quick Tunnel（无固定域名，重启即换）" -ForegroundColor Yellow
    } else {
        Write-Host "       => 无法判断类型" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [无] 本机没有 cloudflared 服务" -ForegroundColor Yellow
    Write-Host "       => 但它可能以【非服务】方式运行。下面继续找进程与可执行文件。" -ForegroundColor Yellow

    # 进程
    $cfProc = Get-Process -Name 'cloudflared' -ErrorAction SilentlyContinue
    if ($cfProc) {
        Write-Host "  [有] 找到 cloudflared 进程 (PID " -NoNewline
        Write-Host ($cfProc.Id -join ',') -NoNewline
        Write-Host ")"
    } else {
        Write-Host "  [无] 也没有 cloudflared 进程在跑"
    }

    # 可执行文件
    $cfExe = Get-Command cloudflared -ErrorAction SilentlyContinue
    $cfPaths = @()
    if ($cfExe) { $cfPaths += $cfExe.Source }
    foreach ($p in @('C:\cloudflared\cloudflared.exe',
                     'C:\Program Files\cloudflared\cloudflared.exe',
                     "$env:LOCALAPPDATA\cloudflared\cloudflared.exe")) {
        if (Test-Path $p) { $cfPaths += $p }
    }
    if ($cfPaths.Count) {
        Write-Host ("  [有] cloudflared.exe: " + (($cfPaths | Select-Object -Unique) -join ' | '))
    } else {
        Write-Host "  [无] 找不到 cloudflared.exe"
    }

    # 计划任务
    $cfTask = Get-ScheduledTask -ErrorAction SilentlyContinue |
        Where-Object { $_.TaskName -like '*cloudflared*' -or $_.TaskName -like '*tunnel*' } |
        Select-Object -First 3
    if ($cfTask) {
        foreach ($t in $cfTask) {
            Write-Host ("  [有] 计划任务: " + $t.TaskName + "  " + $t.State)
        }
    }

    # 启动文件夹
    $startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
    $lnks = @(Get-ChildItem $startup -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like '*cloud*' -or $_.Name -like '*tunnel*' })
    if ($lnks.Count) {
        Write-Host ("  [有] 启动文件夹里有: " + (($lnks | ForEach-Object { $_.Name }) -join ' | '))
    }

    Write-Host "       => 若以上都没有，说明隧道跑在【另一台机器】上，" -ForegroundColor Yellow
    Write-Host "          而 kanban 是从那台机器反代过来的。" -ForegroundColor Yellow
}

# ---------------------------------------------------------- 4
Line "4. cloudflared 配置文件里的 ingress（找 daily 那一条）"
$cfgs = @()
$pname2 = if ($svc) { (Get-CimInstance Win32_Service -Filter "Name='$($svc.Name)'").PathName } else { '' }
if ($pname2 -match '--config\s+"?([^"]+\.ya?ml)"?') { $cfgs += $Matches[1] }
$cfgs += (Join-Path $env:USERPROFILE '.cloudflared\config.yml')
$cfgs += (Join-Path $env:USERPROFILE '.cloudflared\config.yaml')
$cfgs += 'C:\Windows\System32\config\systemprofile\.cloudflared\config.yml'
$foundCfg = $false
foreach ($c in $cfgs) {
    if ($c -and (Test-Path $c)) {
        $foundCfg = $true
        Write-Host ("  配置文件: " + $c) -ForegroundColor Green
        $txt = Get-Content $c -Raw -Encoding UTF8
        Write-Host "  --- ingress 段 ---"
        $lines = Get-Content $c -Encoding UTF8
        $ini = $false
        foreach ($l in $lines) {
            if ($l -match '^\s*ingress\s*:') { $ini = $true }
            if ($ini) { Write-Host ("    " + $l) }
        }
        # 专门检查 daily 的 service 协议
        if ($txt -match '(?s)hostname:\s*daily\.forestkopa\.top.*?service:\s*(\S+)') {
            $svcUrl = $Matches[1]
            Write-Host ""
            Write-Host ("  >>> daily 的 service = " + $svcUrl)
            if ($svcUrl -match '^https://') {
                Write-Host "  >>> [!] 协议是 https，但后端是纯 HTTP —— 这就是 502 的原因！" -ForegroundColor Red
                Write-Host "  >>>     应改为 http://localhost:5190" -ForegroundColor Red
            } elseif ($svcUrl -match '^http://') {
                Write-Host "  >>> [OK] 协议是 http，正确" -ForegroundColor Green
            }
        } else {
            Write-Host ""
            Write-Host "  >>> config.yml 里【没有】daily 的 ingress 规则" -ForegroundColor Yellow
            Write-Host "  >>> 说明 daily 是在 Cloudflare 后台用 Public Hostname 配的" -ForegroundColor Yellow
            Write-Host "  >>> 请去 Zero Trust 后台检查那条记录协议是否为 HTTP" -ForegroundColor Yellow
        }
        break
    }
}
if (-not $foundCfg) {
    Write-Host "  没找到任何 config.yml" -ForegroundColor Yellow
    Write-Host "  => 说明路由是走 Cloudflare 后台 Public Hostname 配的" -ForegroundColor Yellow
}

# ---------------------------------------------------------- 5
Line "5. 本机所有监听端口（确认 5190 是否被别的服务占着）"
$ports = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in @(5180, 5181, 5190, 5191) } |
    Sort-Object LocalPort
if ($ports) {
    foreach ($p in $ports) {
        $pr = (Get-Process -Id $p.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        Write-Host ("  " + $p.LocalAddress + ":" + $p.LocalPort + "  <- " + $pr)
    }
} else {
    Write-Host "  5180/5181/5190/5191 都没有监听" -ForegroundColor Yellow
    Write-Host "  => 连 kanban 都不在这台机器上" -ForegroundColor Yellow
}

# ---------------------------------------------------------- 6
Line "6. 结论"
if (-not $listen) {
    Write-Host "  502 的直接原因：5190 没有服务在监听。" -ForegroundColor Red
    Write-Host "  下一步：先把 daily 看板部署起来（跑 deploy-python.ps1），再回头测域名。" -ForegroundColor Yellow
} else {
    Write-Host "  5190 有服务在听。" -ForegroundColor Green
    Write-Host "  那么 502 的原因大概率是【回源协议/地址】写错，请重点看第 4 节的输出。" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  本脚本只读，没有修改任何东西。"
Write-Host ""
