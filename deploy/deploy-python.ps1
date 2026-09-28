<#
.SYNOPSIS
    AI 日报看板 · 服务器一键部署（Python 版 · 适配服务器已有 Python 3.8）

.DESCRIPTION
    适用于服务器上已装 Python 3.8 的情况，无需 exe。

    在服务器上注册两个东西：
      1. NSSM 服务 ai-briefing-server  —— 常驻静态文件服务（端口 5190）
      2. 计划任务 ai-briefing-update    —— 每天 8:30 跑抓取更新

    与 deploy-nssm.ps1（exe 版）的区别：
      - 用服务器已有的 Python 建独立 venv，装 feedparser==6.0.12
      - 计划任务直接调用 venv 里的 python.exe 跑 cli.py
      - 不依赖任何打包产物，脚本全透明、好调试

    重要：Python 3.8 只能用 feedparser <= 6.0.12（6.0.13+ 要求 >=3.10）

.NOTES
    运行前请确认：
      - 已把 server.js / cli.py / fetch_rss.py / build.py / clean_cache.py 放到同一目录
      - 已把 node.exe 加入 PATH 或指定 -NodePath
      - 以管理员身份运行
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "D:\ai-daily-briefing",
    [int]$Port = 5190,
    [string]$PythonPath = "",
    [string]$NodePath = "",
    [string]$NssmPath = "",
    [string]$TaskTime = "08:30",
    [string]$FeedparserVersion = "6.0.12",
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

Say "=============================================================="
Say "  AI 日报看板 · 服务器部署（Python 版）"
Say "=============================================================="
Say ""

if (-not (Test-Admin)) {
    Fail "需要管理员权限。请右键 PowerShell -> 以管理员身份运行。"
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Ok "脚本目录: $ScriptDir"

# ------------------------------------------------------------------ 找 Python
# 注意：Windows 自带的 Microsoft Store「应用别名」会在 PATH 前面放一个
# C:\Users\<u>\AppData\Local\Microsoft\WindowsApps\python.exe，**它是 0 字节的占位 stub**，
# Get-Command 能查到它、却根本跑不了。必须显式排除，否则后面 `python -m venv` 必然失败。
function Test-RealPython {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path $Path)) { return $false }
    # 0 字节 / 极小体积 = 应用商店占位符，不是真解释器
    try {
        if ((Get-Item $Path).Length -lt 10000) { return $false }
    } catch { return $false }
    # 真的能跑起来并报出 3.x 版本才算数
    $v = (& $Path -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
    return ($v -match '^\d+\.\d+$')
}

if (-not $PythonPath) {
    $cands = @()
    # python / py 都要试：Windows 上很可能 python 只指向应用商店占位符，
    # 而真正的解释器只能通过 py 启动器（C:\Windows\py.exe）找到。
    foreach ($name in @('python', 'py')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $cands += $cmd.Source }
    }
    # 常见真实安装位置，避免只依赖 PATH
    $cands += (Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { $_.FullName })
    $cands += (Get-ChildItem "C:\Python*\python.exe" -ErrorAction SilentlyContinue |
        ForEach-Object { $_.FullName })
    $cands += (Get-ChildItem "C:\Program Files\Python*\python.exe" -ErrorAction SilentlyContinue |
        ForEach-Object { $_.FullName })

    # 补充：用 py 启动器列出「已注册但不在 PATH」的解释器（老安装常这样）
    $pyLauncher = (Get-Command py -ErrorAction SilentlyContinue).Source
    if ($pyLauncher) {
        try {
            $listed = (& $pyLauncher -0p) 2>$null
            foreach ($line in $listed) {
                if ($line -match '([A-Za-z]:\\[^\s].*python\.exe)') { $cands += $Matches[1] }
            }
        } catch { }
    }

    foreach ($c in $cands) {
        if (Test-RealPython $c) { $PythonPath = $c; break }
        elseif ($c -like '*WindowsApps*') {
            Warn "跳过应用商店占位符（0 字节，不是真 Python）: $c"
        }
    }
}
if (-not $PythonPath -or -not (Test-Path $PythonPath)) {
    Fail "找不到可用的 python.exe。"
    Say "  常见原因：只装了 Microsoft Store 版，它给的是 0 字节占位符，无法建 venv。"
    Say "  解决：装 python.org 版，或用 -PythonPath 指定真实路径，例如："
    Say "      .\deploy-python.ps1 -PythonPath `"C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe`""
    exit 1
}
if (-not (Test-RealPython $PythonPath)) {
    Fail "$PythonPath 不是一个可用的 Python 解释器（可能是 0 字节占位符）。"
    Say "  用 -PythonPath 指定真实 python.exe。"
    exit 1
}
$pyVer = (& $PythonPath -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null)
if (-not $pyVer) {
    Fail "无法从 $PythonPath 取得版本号，它可能不是有效的 Python。"
    exit 1
}
Ok "Python: $PythonPath  (版本 $pyVer)"

$major, $minor = ($pyVer -split '\.')[0..1] | ForEach-Object { [int]$_ }
if ($major -eq 3 -and $minor -lt 6) {
    Fail "Python $pyVer 过旧（需 >=3.6）。"
    exit 1
}
if ($major -eq 3 -and $minor -ge 10) {
    $FeedparserVersion = "6.0.14"
    Warn "检测到 Python $pyVer，改用 feedparser $FeedparserVersion"
} elseif ($major -eq 3 -and $minor -le 9) {
    Warn "检测到 Python $pyVer，使用 feedparser $FeedparserVersion（6.0.13+ 需要 3.10+）"
}

# ------------------------------------------------------------------ 找 nssm
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

# ------------------------------------------------------------------ 找 node
if (-not $NodePath) {
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) { $NodePath = $cmd.Source }
    elseif (Test-Path "C:\Program Files\nodejs\node.exe") {
        $NodePath = "C:\Program Files\nodejs\node.exe"
    }
}
if (-not $NodePath -or -not (Test-Path $NodePath)) {
    Fail "找不到 node.exe。请先装 Node.js（>=16 即可），或用 -NodePath 指定。"
    exit 1
}
Ok "Node: $NodePath"

# ------------------------------------------------------------------ 端口检查
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    $owner = (Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
    Fail "端口 $Port 已被占用（进程: $owner）。用 -Port 换一个（如 5191）。"
    exit 1
}
Ok "端口 $Port 可用"

# ------------------------------------------------------------------ 需要同目录的文件
$NeedFiles = @("server.js", "cli.py", "fetch_rss.py", "build.py", "clean_cache.py")
foreach ($f in $NeedFiles) {
    $p = Join-Path $ScriptDir $f
    if (-not (Test-Path $p)) { Fail "缺少文件: $p"; exit 1 }
}
Ok "脚本文件齐全（$($NeedFiles.Count) 个）"

# ================================================================== 1. 建目录
Say ""
Say "[1/6] 准备安装目录..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "logs") | Out-Null
foreach ($f in $NeedFiles) {
    Copy-Item (Join-Path $ScriptDir $f) (Join-Path $InstallDir $f) -Force
}
Ok "已安装到 $InstallDir"

# ================================================================== 2. 建 venv
Say ""
Say "[2/6] 创建虚拟环境并安装 feedparser..."
$Venv = Join-Path $InstallDir "venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Say "      正在创建 venv（用 $PythonPath）..."
    # 不用 | Out-Null 吞掉输出：venv 失败时错误信息必须让用户看到
    & $PythonPath -m venv $Venv
    $venvRc = $LASTEXITCODE
    if ($venvRc -ne 0 -or -not (Test-Path $VenvPy)) {
        Fail "创建 venv 失败（退出码 $venvRc）。"
        Say ""
        Say "  常见原因与解法："
        Say "    1) 用的 python.exe 是 Microsoft Store 的 0 字节占位符"
        Say "       -> 用 -PythonPath 指定真实解释器，例如："
        Say "          .\deploy-python.ps1 -PythonPath `"C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe`""
        Say "    2) Python 安装不完整（缺 venv 模块）"
        Say "       -> 重装 Python，安装时勾选 pip 与 venv"
        Say "    3) 目标目录无写权限"
        Say "       -> 确认以管理员身份运行，且 $InstallDir 可写"
        Say ""
        Say "  也可临时改用 exe 模式（不需要 Python）："
        Say "      .\deploy-nssm.ps1"
        exit 1
    }
    Ok "venv 已创建: $Venv"
} else {
    Ok "venv 已存在，复用"
}

# 升级 pip（老版本 Python 自带 pip 很旧）
& $VenvPy -m pip install --upgrade pip --quiet --disable-pip-version-check 2>&1 | Out-Null

# 装 feedparser —— 指定版本，兼容老 Python
Say "      正在安装 feedparser==$FeedparserVersion ..."
& $VenvPy -m pip install "feedparser==$FeedparserVersion" --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
    Fail "安装 feedparser 失败。检查服务器能否访问 pypi.org（或配国内镜像）。"
    Warn "可试：& `"$VenvPy`" -m pip install feedparser==$FeedparserVersion -i https://pypi.tuna.tsinghua.edu.cn/simple"
    exit 1
}
$fpVer = (& $VenvPy -c "import feedparser; print(feedparser.__version__)" 2>$null)
if (-not $fpVer) {
    Fail "feedparser 装上了但导入失败，venv 可能损坏。删掉 $Venv 重跑本脚本。"
    exit 1
}
Ok "feedparser $fpVer 已安装"

# ================================================================== 3. 注册服务
Say ""
Say "[3/6] 注册 NSSM 服务 $SvcName ..."
& cmd /c "`"$NssmPath`" stop $SvcName 2>nul" | Out-Null
& cmd /c "`"$NssmPath`" remove $SvcName confirm 2>nul" | Out-Null
Start-Sleep -Milliseconds 500

& $NssmPath install $SvcName $NodePath "server.js --port $Port --root `"$InstallDir\data`" --py `"$VenvPy`" --cli `"$InstallDir\cli.py`" --cooldown 60"
if ($LASTEXITCODE -ne 0) { Fail "NSSM 注册失败"; exit 1 }

& $NssmPath set $SvcName AppDirectory $InstallDir | Out-Null
& $NssmPath set $SvcName DisplayName "AI Daily Briefing (static, port $Port)" | Out-Null
& $NssmPath set $SvcName Description "AI 日报看板静态服务 - 只读，端口 $Port" | Out-Null
& $NssmPath set $SvcName Start SERVICE_AUTO_START | Out-Null
& $NssmPath set $SvcName AppExit Default Restart | Out-Null
& $NssmPath set $SvcName AppStdout (Join-Path $InstallDir "logs\server-out.log") | Out-Null
& $NssmPath set $SvcName AppStderr (Join-Path $InstallDir "logs\server-err.log") | Out-Null
& $NssmPath set $SvcName AppRotateFiles 1 | Out-Null
& $NssmPath set $SvcName AppRotateBytes 1048576 | Out-Null
Ok "服务已注册（开机自启、崩溃自动重启）"

# ================================================================== 4. 首次更新
Say ""
Say "[4/6] 运行首次抓取（生成首页数据）..."
Push-Location $InstallDir
try {
    & $VenvPy (Join-Path $InstallDir "cli.py") --out (Join-Path $InstallDir "data") --hours 48 --keep-days 30
    if ($LASTEXITCODE -ne 0) {
        Warn "首次抓取未成功（可能是网络/防火墙）。服务仍会启动，稍后可手动重跑。"
    } else {
        Ok "首次数据已生成"
    }
} finally {
    Pop-Location
}

# ================================================================== 5. 启动服务
Say ""
Say "[5/6] 启动服务..."
& $NssmPath start $SvcName | Out-Null
Start-Sleep -Seconds 3

$local = "http://127.0.0.1:$Port/healthz"
try {
    $r = Invoke-WebRequest -Uri $local -UseBasicParsing -TimeoutSec 10
    Ok "本地探活通过: HTTP $($r.StatusCode)"
    Say "    $($r.Content.Substring(0, [Math]::Min(150, $r.Content.Length)))"
} catch {
    Fail "本地探活失败: $_"
    Warn "看日志: Get-Content `"$InstallDir\logs\server-err.log`" -Tail 30"
}

# ================================================================== 6. 计划任务
Say ""
Say "[6/6] 注册每日更新计划任务..."
if ($SkipTask) {
    Warn "已跳过（-SkipTask）"
} else {
    $act = New-ScheduledTaskAction -Execute $VenvPy `
        -Argument "`"$InstallDir\cli.py`" --out `"$InstallDir\data`" --hours 48 --keep-days 30" `
        -WorkingDirectory $InstallDir
    $trg = New-ScheduledTaskTrigger -Daily -At $TaskTime
    $set = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    $prn = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $act -Trigger $trg `
        -Settings $set -Principal $prn -Description "AI 日报看板每日更新（抓 RSS + 生成 HTML）" | Out-Null
    Ok "计划任务已注册（每天 $TaskTime，以 SYSTEM 身份运行）"
}

# ================================================================== 完成
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
Say "  ---- 日常运维 ----"
Say "      服务状态: & `"$NssmPath`" status $SvcName"
Say "      重启服务: & `"$NssmPath`" restart $SvcName"
Say "      手动更新: & `"$VenvPy`" `"$InstallDir\cli.py`" --out `"$InstallDir\data`""
Say "      服务日志: Get-Content `"$InstallDir\logs\server-err.log`" -Tail 30"
Say "      任务记录: schtasks /Query /TN $TaskName /V /FO LIST"
Say "      卸载:     & `"$NssmPath`" stop $SvcName; & `"$NssmPath`" remove $SvcName confirm"
Say "                schtasks /Delete /TN $TaskName /F"
Say ""
