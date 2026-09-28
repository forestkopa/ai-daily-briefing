<#
.SYNOPSIS
    AI 日报看板 · 服务器一键部署（Windows · 管理员 PowerShell）

.DESCRIPTION
    在服务器上注册两个东西：
      1. NSSM 服务 ai-briefing-server  —— 常驻静态文件服务（端口 5190）
      2. 计划任务 ai-briefing-update    —— 每天 8:30 跑抓取更新

    设计原则：
      - 只读静态服务，绝不写 kanban 的任何文件
      - 服务名 / 端口 / 计划任务名全部带 ai-briefing 前缀，与 kanban 完全隔离
      - 全程幂等：重复运行会先移除旧的再装
      - 不自动改 kanban 的 config.yml —— 隧道 ingress 需手动增补（脚本会打印片段）

.NOTES
    运行前请确认：
      - 已把 deploy-nssm.ps1 / nssm.exe / server.js / ai-briefing-update.exe 放到同一目录
      - 已把 node.exe 加入 PATH 或指定 -NodePath
      - 以管理员身份运行
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "D:\ai-daily-briefing",
    [int]$Port = 5190,
    [string]$NodePath = "",
    [string]$NssmPath = "",
    [string]$TaskTime = "08:30",
    [switch]$SkipTask
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$SvcName  = "ai-briefing-server"
$TaskName = "ai-briefing-update"

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "[v] $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "[!] $m" -ForegroundColor Yellow }
function Fail ($m) { Write-Host "[x] $m" -ForegroundColor Red }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ------------------------------------------------------------------ 0. 前置检查
Say "=============================================================="
Say "  AI 日报看板 · 服务器部署"
Say "=============================================================="
Say ""

if (-not (Test-Admin)) {
    Fail "需要管理员权限。请右键 PowerShell -> 以管理员身份运行。"
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerJs  = Join-Path $ScriptDir "server.js"
foreach ($f in @($ServerJs)) {
    if (-not (Test-Path $f)) { Fail "缺少文件: $f"; exit 1 }
}
Ok "脚本目录: $ScriptDir"

# 找 nssm.exe
if (-not $NssmPath) {
    foreach ($c in @(
        (Join-Path $ScriptDir "nssm.exe"),
        (Join-Path $ScriptDir "nssm-2.24\win64\nssm.exe"),
        "C:\nssm\nssm.exe"
    )) {
        if (Test-Path $c) { $NssmPath = $c; break }
    }
}
if (-not $NssmPath -or -not (Test-Path $NssmPath)) {
    Fail "找不到 nssm.exe。请把 nssm.exe 放到脚本同目录，或用 -NssmPath 指定。"
    exit 1
}
Ok "NSSM: $NssmPath"

# 找 node.exe
if (-not $NodePath) {
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) { $NodePath = $cmd.Source }
    elseif (Test-Path "C:\Program Files\nodejs\node.exe") {
        $NodePath = "C:\Program Files\nodejs\node.exe"
    }
}
if (-not $NodePath -or -not (Test-Path $NodePath)) {
    Fail "找不到 node.exe。请先装 Node.js >=22，或用 -NodePath 指定。"
    exit 1
}
Ok "Node: $NodePath"

# 端口占用检查
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    $owner = (Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Fail "端口 $Port 已被占用（进程: $owner）。用 -Port 换一个（如 5191）。"
    exit 1
}
Ok "端口 $Port 可用"

# ------------------------------------------------------------------ 1. 准备目录
Say ""
Say "[1/5] 准备安装目录..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "data") | Out-Null
Copy-Item $ServerJs (Join-Path $InstallDir "server.js") -Force
Ok "已安装到 $InstallDir"

# 如果同目录带了 exe，一并拷过去
$exeSrc = Join-Path $ScriptDir "ai-briefing-update.exe"
$exeDst = Join-Path $InstallDir "ai-briefing-update.exe"
if (Test-Path $exeSrc) {
    Copy-Item $exeSrc $exeDst -Force
    Ok "已拷贝更新器 exe"
} else {
    Warn "未找到 ai-briefing-update.exe —— 将跳过每日更新任务。"
    $SkipTask = $true
}

# ------------------------------------------------------------------ 2. 注册服务
Say ""
Say "[2/5] 注册 NSSM 服务 $SvcName ..."

# 幂等：先停再删（服务不存在时 nssm 返回非零，用 cmd /c 包住避免中断）
& cmd /c "`"$NssmPath`" stop $SvcName 2>nul" | Out-Null
& cmd /c "`"$NssmPath`" remove $SvcName confirm 2>nul" | Out-Null
Start-Sleep -Milliseconds 500

& $NssmPath install $SvcName $NodePath "server.js --port $Port --root `"$InstallDir\data`" --py `"$exeDst`" --cli `"`" --cooldown 60"
if ($LASTEXITCODE -ne 0) { Fail "NSSM 注册失败"; exit 1 }
# 说明：--py 指向 exe 本身、--cli 传空 —— server.js 以 `exe --out <data>` 方式调用它做页面刷新。

& $NssmPath set $SvcName AppDirectory $InstallDir | Out-Null
& $NssmPath set $SvcName DisplayName "AI Daily Briefing (static, port $Port)" | Out-Null
& $NssmPath set $SvcName Description "AI 日报看板静态服务 - 只读，端口 $Port" | Out-Null
& $NssmPath set $SvcName Start SERVICE_AUTO_START | Out-Null
& $NssmPath set $SvcName AppStdout (Join-Path $InstallDir "data\server-out.log") | Out-Null
& $NssmPath set $SvcName AppStderr (Join-Path $InstallDir "data\server-err.log") | Out-Null
& $NssmPath set $SvcName AppRotateFiles 1 | Out-Null
& $NssmPath set $SvcName AppRotateBytes 1048576 | Out-Null
Ok "服务已注册（开机自启）"

# ------------------------------------------------------------------ 3. 首次更新
Say ""
Say "[3/5] 运行首次抓取（生成首页数据）..."
if (Test-Path $exeDst) {
    & $exeDst --out (Join-Path $InstallDir "data") --hours 48 --keep-days 30
    if ($LASTEXITCODE -ne 0) {
        Warn "首次抓取未成功（可能是网络/防火墙）。服务仍会启动，稍后可手动重跑。"
    } else {
        Ok "首次数据已生成"
    }
} else {
    Warn "跳过（无 exe）"
}

# ------------------------------------------------------------------ 4. 启动服务
Say ""
Say "[4/5] 启动服务..."
& $NssmPath start $SvcName | Out-Null
Start-Sleep -Seconds 3

$local = "http://127.0.0.1:$Port/healthz"
try {
    $r = Invoke-WebRequest -Uri $local -UseBasicParsing -TimeoutSec 10
    Ok "本地探活通过: $($r.StatusCode) $($r.Content.Substring(0, [Math]::Min(120, $r.Content.Length)))"
} catch {
    Fail "本地探活失败: $_"
    Warn "看日志: Get-Content `"$InstallDir\data\server-err.log`" -Tail 30"
}

# ------------------------------------------------------------------ 5. 计划任务
Say ""
Say "[5/5] 注册每日更新计划任务..."
if ($SkipTask) {
    Warn "已跳过（无 exe 或指定了 -SkipTask）"
} else {
    $act = New-ScheduledTaskAction -Execute $exeDst `
        -Argument "--out `"$InstallDir\data`" --hours 48 --keep-days 30" `
        -WorkingDirectory $InstallDir
    $trg = New-ScheduledTaskTrigger -Daily -At $TaskTime
    $set = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    $prn = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $act -Trigger $trg `
        -Settings $set -Principal $prn -Description "AI 日报看板每日更新（抓 RSS + 生成 HTML）" | Out-Null
    Ok "计划任务已注册（每天 $TaskTime）"
}

# ------------------------------------------------------------------ 完成
Say ""
Say "=============================================================="
Ok "部署完成"
Say "=============================================================="
Say ""
Say "  本地访问: http://127.0.0.1:$Port"
Say "  探活检查: http://127.0.0.1:$Port/healthz"
Say ""
Say "  ---- 还需要手动做一步：隧道域名 ----"
Say "  在 cloudflared 的 config.yml 里，ingress 列表【兜底条目的前面】插入："
Say ""
Say "      - hostname: daily.forestkopa.top"
Say "        service: http://localhost:$Port"
Say ""
Say "  注意：ingress 是顺序匹配，具体域名必须在最后那条无 hostname 的兜底项之前。"
Say "  然后在 Cloudflare 后台给 daily.forestkopa.top 加 CNAME 指向隧道。"
Say ""
Say "  ---- 重启 cloudflared ----"
Say "  先确认它的服务名/运行方式，再重启（会让 kanban 公网闪断 3-5 秒）："
Say "      Get-Service | Where-Object { `$_.Name -like '*cloudflared*' }"
Say "      # 若是服务:  Restart-Service <服务名>"
Say "      # 若在任务计划: schtasks /End /TN <任务名>; schtasks /Run /TN <任务名>"
Say ""
Say "  常用运维命令："
Say "      状态: & `"$NssmPath`" status $SvcName"
Say "      重启: & `"$NssmPath`" restart $SvcName"
Say "      日志: Get-Content `"$InstallDir\data\server-err.log`" -Tail 30"
Say "      卸载: & `"$NssmPath`" stop $SvcName; & `"$NssmPath`" remove $SvcName confirm"
Say ""
