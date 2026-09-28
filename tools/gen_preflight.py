# -*- coding: utf-8 -*-
"""生成 preflight.ps1 —— 部署前置自检。

为什么要有它：部署的繁琐感有一半来自「不知道会踩什么坑」。
这个脚本在动手前把服务器扫一遍，逐项告诉用户「已就绪 / 有问题 / 需要决定」，
把「现场发现问题」提前到「动手之前」。

它只读，不改任何东西。可以随便跑。

设计原则：
  - 每项检查独立，一项失败不影响其余
  - 输出分三级：OK（绿）/ WARN（黄，需注意但不阻塞）/ BLOCK（红，必须先解决）
  - 结尾给一张总结表 + 下一步命令，用户照着做即可
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist_package" / "preflight.ps1"

PS1 = r'''<#
.SYNOPSIS
    AI 日报看板 · 部署前置自检（只读，不修改任何东西）

.DESCRIPTION
    在部署前把服务器扫一遍，逐项报告：
      [OK]    已就绪
      [!]     需注意，一般不阻塞
      [x]     必须先解决，否则部署会失败

    然后给出「还差什么」和「下一步跑什么」。

.PARAMETER Port
    计划使用的端口，默认 5190

.PARAMETER InstallDir
    计划安装目录，默认 D:\ai-daily-briefing

.EXAMPLE
    .\preflight.ps1
    .\preflight.ps1 -Port 5190 -InstallDir "D:\ai-daily-briefing"
#>
[CmdletBinding()]
param(
    [int]$Port = 5190,
    [string]$InstallDir = "D:\ai-daily-briefing"
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$results = New-Object System.Collections.ArrayList

function Add-Result {
    param([string]$Level, [string]$Item, [string]$Detail)
    [void]$results.Add([pscustomobject]@{ Level = $Level; Item = $Item; Detail = $Detail })
    $color = switch ($Level) {
        'OK'   { 'Green' }
        'WARN' { 'Yellow' }
        'BLOCK'{ 'Red' }
        default { 'Gray' }
    }
    $tag = switch ($Level) {
        'OK'   { '[v]' }
        'WARN' { '[!]' }
        'BLOCK'{ '[x]' }
        default { '[ ]' }
    }
    Write-Host ("{0} {1,-26} {2}" -f $tag, $Item, $Detail) -ForegroundColor $color
}

Write-Host "=============================================================="
Write-Host "  AI 日报看板 · 部署前置自检"
Write-Host "=============================================================="
Write-Host "  目标端口: $Port"
Write-Host "  安装目录: $InstallDir"
Write-Host ""

# ---------------------------------------------------------------- 1. 管理员权限
Write-Host "-- 1. 权限与系统 --"
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    Add-Result 'OK' '管理员权限' '已具备'
} else {
    Add-Result 'BLOCK' '管理员权限' '请用「以管理员身份运行」重开 PowerShell'
}

$os = (Get-CimInstance Win32_OperatingSystem)
Add-Result 'OK' '操作系统' "$($os.Caption.Trim()) (build $($os.BuildNumber))"

# ---------------------------------------------------------------- 2. 端口
Write-Host ""
Write-Host "-- 2. 端口 --"
$portBusy = $false
try {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        $portBusy = $true
        $procId = ($conns | Select-Object -First 1).OwningProcess
        $pname = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
        Add-Result 'BLOCK' "端口 $Port" "已被占用（PID $procId / $pname）"
    } else {
        Add-Result 'OK' "端口 $Port" '空闲'
    }
} catch {
    $net = netstat -ano | Select-String ":$Port\s"
    if ($net) {
        $portBusy = $true
        Add-Result 'BLOCK' "端口 $Port" '疑似被占用（netstat 检测到）'
    } else {
        Add-Result 'OK' "端口 $Port" '空闲'
    }
}

# ---------------------------------------------------------------- 3. Node
Write-Host ""
Write-Host "-- 3. Node.js --"
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $nv = (& node --version) 2>$null
    Add-Result 'OK' 'Node.js' "$nv  ($($node.Source))"
} else {
    Add-Result 'BLOCK' 'Node.js' '未安装或不在 PATH —— server.js 需要它'
}

# ---------------------------------------------------------------- 4. Python
Write-Host ""
Write-Host "-- 4. Python --"

# Windows 的 Microsoft Store「应用别名」会在 PATH 前面放一个 0 字节的
# WindowsApps\python.exe 占位 stub，Get-Command 查得到但跑不了，
# 用它建 venv 必然失败。必须显式识别出来。
function Test-RealPython {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path $Path)) { return $false }
    try { if ((Get-Item $Path).Length -lt 10000) { return $false } } catch { return $false }
    $v = (& $Path -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
    return ($v -match '^\d+\.\d+$')
}

$pyCands = @()
foreach ($cand in @('python', 'py')) {
    $c = Get-Command $cand -ErrorAction SilentlyContinue
    if ($c) { $pyCands += $c.Source }
}
$pyCands += (Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | ForEach-Object { $_.FullName })
$pyCands += (Get-ChildItem "C:\Python*\python.exe" -ErrorAction SilentlyContinue |
    ForEach-Object { $_.FullName })
$pyCands += (Get-ChildItem "C:\Program Files\Python*\python.exe" -ErrorAction SilentlyContinue |
    ForEach-Object { $_.FullName })

# 补充：py 启动器能列出「已注册但不在 PATH」的解释器
$pyLauncher = (Get-Command py -ErrorAction SilentlyContinue).Source
if ($pyLauncher) {
    try {
        foreach ($line in ((& $pyLauncher -0p) 2>$null)) {
            if ($line -match '([A-Za-z]:\\[^\s].*python\.exe)') { $pyCands += $Matches[1] }
        }
    } catch { }
}

$pyReal = $null
$pyStub = $null
foreach ($c in $pyCands) {
    if (Test-RealPython $c) { $pyReal = $c; break }
    elseif ($c -like '*WindowsApps*') { $pyStub = $c }
}

if ($pyReal) {
    $pyVer = (& $pyReal -c "import sys; print('%d.%d.%d' % sys.version_info[:3])") 2>$null
    $parts = $pyVer -split '\.'
    $maj = [int]$parts[0]; $min = [int]$parts[1]
    if ($maj -eq 3 -and $min -ge 10) {
        Add-Result 'OK' 'Python' "$pyVer ($pyReal) → 将装 feedparser 6.0.14"
    } elseif ($maj -eq 3 -and $min -ge 6) {
        Add-Result 'OK' 'Python' "$pyVer ($pyReal) → 将装 feedparser 6.0.12"
    } else {
        Add-Result 'BLOCK' 'Python' "$pyVer 太旧（需 3.6+）"
    }
    if ($pyStub) {
        Add-Result 'WARN' '应用商店占位符' "PATH 里还有 $pyStub（0 字节，不可用）—— 部署脚本已能跳过它"
    }
} elseif ($pyStub) {
    Add-Result 'BLOCK' 'Python' "PATH 里只有应用商店占位符 $pyStub（0 字节，无法建 venv）"
    Write-Host "      -> 装 python.org 版，或改用 exe 模式 deploy-nssm.ps1" -ForegroundColor Yellow
} else {
    Add-Result 'WARN' 'Python' '未找到 —— 只能走 exe 模式（deploy-nssm.ps1）'
}

# ---------------------------------------------------------------- 5. pypi 连通性
Write-Host ""
Write-Host "-- 5. 网络 --"
try {
    $r = Invoke-WebRequest 'https://pypi.org/simple/' -UseBasicParsing -TimeoutSec 12 -Method Head
    Add-Result 'OK' 'pypi.org' "可达 (HTTP $($r.StatusCode))"
} catch {
    Add-Result 'WARN' 'pypi.org' '不可达 —— 需用国内镜像，或改走 exe 模式'
}

# ---------------------------------------------------------------- 6. nssm
Write-Host ""
Write-Host "-- 6. 服务管理器 nssm --"
$nssmCandidates = @(
    'C:\nssm\nssm.exe',
    (Join-Path $PSScriptRoot 'nssm.exe'),
    'C:\Users\Administrator\WorkBuddy\2026-08-20-10-00-21\project-kanban\tools\nssm-2.24\win64\nssm.exe'
)
$nssm = $null
foreach ($c in $nssmCandidates) {
    if ($c -and (Test-Path $c)) { $nssm = $c; break }
}
if (-not $nssm) {
    $nc = Get-Command nssm -ErrorAction SilentlyContinue
    if ($nc) { $nssm = $nc.Source }
}
if ($nssm) {
    Add-Result 'OK' 'nssm.exe' $nssm
} else {
    Add-Result 'BLOCK' 'nssm.exe' '未找到 —— 部署包内已附带，请从包里取'
}

# ---------------------------------------------------------------- 7. cloudflared
Write-Host ""
Write-Host "-- 7. Cloudflare 隧道 --"
$cfsvc = Get-Service | Where-Object {
    $_.Name -like '*cloudflared*' -or $_.DisplayName -like '*cloudflared*'
} | Select-Object -First 1
# 供结尾「下一步」提示判断用
$hasCfSvc = [bool]$cfsvc

if ($cfsvc) {
    $status = $cfsvc.Status
    $lvl = if ($status -eq 'Running') { 'OK' } else { 'WARN' }
    Add-Result $lvl 'cloudflared 服务' "$($cfsvc.Name) —— $status"

    # 判断隧道类型
    $pname = (Get-CimInstance Win32_Service -Filter "Name='$($cfsvc.Name)'").PathName
    if ($pname -match 'tunnel\s+run') {
        Add-Result 'OK' '隧道类型' '命名隧道（可配固定域名）'
        $hasIngress = $false
        $cfgPaths = @(
            (Join-Path $env:USERPROFILE '.cloudflared\config.yml'),
            'C:\Windows\System32\config\systemprofile\.cloudflared\config.yml'
        )
        if ($pname -match '--config\s+"?([^"]+\.yml)"?') { $cfgPaths = @($Matches[1]) + $cfgPaths }
        foreach ($cp in $cfgPaths) {
            if (Test-Path $cp) {
                $txt = Get-Content $cp -Raw -Encoding UTF8
                if ($txt -match '(?m)^\s*ingress\s*:') {
                    $hasIngress = $true
                    Add-Result 'OK' 'config.yml ingress' $cp
                    if ($txt -match '(?m)^\s*-\s*hostname\s*:\s*daily\.') {
                        Add-Result 'OK' 'daily 域名' '已在 ingress 中'
                    } else {
                        Add-Result 'WARN' 'daily 域名' '尚未加入 —— 跑 add-ingress.ps1'
                    }
                }
                break
            }
        }
        if (-not $hasIngress) {
            Add-Result 'WARN' 'config.yml' '没找到带 ingress 的配置文件'
        }
    } elseif ($pname -match '--url') {
        Add-Result 'WARN' '隧道类型' 'Quick Tunnel（无固定域名）—— 需先建命名隧道'
    } else {
        Add-Result 'WARN' '隧道类型' '无法判断 —— 手工确认'
    }
} else {
    Add-Result 'WARN' 'cloudflared' '未检测到 cloudflared 服务 —— 若只在内网访问可忽略；要用 daily.forestkopa.top 公网域名则必须先装好隧道'
}

# ---------------------------------------------------------------- 8. 已有服务隔离性
Write-Host ""
Write-Host "-- 8. 与 kanban 的隔离 --"
$kanban = Get-Service | Where-Object { $_.Name -like '*kanban*' } | Select-Object -First 1
if ($kanban) {
    Add-Result 'OK' 'kanban 服务' "$($kanban.Name) —— $($kanban.Status)（不影响）"
} else {
    Add-Result 'OK' 'kanban 服务' '本机未检测到（可能在别的机器）'
}
if (Test-Path $InstallDir) {
    $cnt = (Get-ChildItem $InstallDir -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count
    # 已有 data\ 就是有历史归档，要特别提醒（但不会被删）
    $hasData = Test-Path (Join-Path $InstallDir 'data')
    if ($hasData) {
        $arch = @(Get-ChildItem (Join-Path $InstallDir 'data') -Filter '*.html' -ErrorAction SilentlyContinue).Count
        Add-Result 'WARN' '安装目录' "$InstallDir 已存在（$cnt 项，含 data\ 历史归档 $arch 个）—— 部署脚本只覆盖程序文件，不会删 data\"
    } else {
        Add-Result 'WARN' '安装目录' "$InstallDir 已存在（$cnt 项）—— 部署脚本只覆盖 5 个程序文件，不删其它内容"
    }
} else {
    Add-Result 'OK' '安装目录' "$InstallDir 不存在（将被创建）"
}

# ---------------------------------------------------------------- 总结
Write-Host ""
Write-Host "=============================================================="
Write-Host "  自检总结"
Write-Host "=============================================================="

$blocked = @($results | Where-Object Level -eq 'BLOCK')
$warned  = @($results | Where-Object Level -eq 'WARN')
$oked    = @($results | Where-Object Level -eq 'OK')

Write-Host ("  就绪 {0} 项    注意 {1} 项    阻塞 {2} 项" -f $oked.Count, $warned.Count, $blocked.Count)
Write-Host ""

if ($blocked.Count -gt 0) {
    Write-Host "  必须先解决：" -ForegroundColor Red
    $blocked | ForEach-Object { Write-Host "    - $($_.Item): $($_.Detail)" -ForegroundColor Red }
    Write-Host ""
}
if ($warned.Count -gt 0) {
    Write-Host "  建议关注：" -ForegroundColor Yellow
    $warned | ForEach-Object { Write-Host "    - $($_.Item): $($_.Detail)" -ForegroundColor Yellow }
    Write-Host ""
}

if ($blocked.Count -eq 0) {
    Write-Host "  >>> 可以开始部署了" -ForegroundColor Green
    Write-Host ""
    Write-Host "  下一步（把部署包解压后，在包里执行）："
    Write-Host "      .\deploy-python.ps1 -Port $Port -InstallDir `"$InstallDir`""
    Write-Host ""
    if ($hasCfSvc) {
        Write-Host "  部署完再配域名（一次就好，之后不用管）："
        Write-Host "      .\add-ingress.ps1 -Hostname daily.forestkopa.top -Port $Port"
    } else {
        Write-Host "  ⚠ 本机没检测到 cloudflared 服务，所以公网域名暂时还通不了。" -ForegroundColor Yellow
        Write-Host "    两条路（详见 Cloudflare_操作清单.md）：" -ForegroundColor Yellow
        Write-Host "      A) 本机装 cloudflared + 建隧道 → 再跑 .\add-ingress.ps1" -ForegroundColor Yellow
        Write-Host "      B) 若隧道跑在别的机器上 → 在 Cloudflare Zero Trust 后台" -ForegroundColor Yellow
        Write-Host "         加 Public Hostname：daily.forestkopa.top → http://<本机IP>:$Port" -ForegroundColor Yellow
        Write-Host "         （Type 必须选 HTTP，不要选 HTTPS）" -ForegroundColor Yellow
    }
} else {
    Write-Host "  >>> 先解决上面标红的项，再跑一次本脚本" -ForegroundColor Red
}

Write-Host ""
Write-Host "  本脚本只读，没有修改任何东西。"
Write-Host ""
'''

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_bytes(b'\xef\xbb\xbf' + PS1.encode('utf-8'))
raw = OUT.read_bytes()
print(f'已生成: {OUT}')
print(f'  体积: {raw.__len__():,} B')
print(f'  BOM : {raw[:3] == b"\xef\xbb\xbf"}')
print(f'  Tab : {"有（需检查）" if b"\t" in raw else "无"}')
