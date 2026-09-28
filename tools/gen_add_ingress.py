# -*- coding: utf-8 -*-
"""生成 add-ingress.ps1 —— 自动、安全地把 daily 域名写进 cloudflared 的 ingress。

为什么要有它：手工改 YAML 有 3 个坑（Tab、缩进、兜底条目的顺序），
改坏一个字符整条隧道就起不来，连 kanban 一起挂。这个脚本把风险消掉：
  - 自动定位 config.yml（用户目录 / SYSTEM 目录）
  - 自动识别隧道类型（命名隧道 vs Quick Tunnel）
  - 备份 → 检查是否已存在 → 插到兜底条目之前 → 校验后写回
  - 校验不过自动回滚，绝不留下坏文件

产物：dist_package/add-ingress.ps1（UTF-8 BOM）
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist_package" / "add-ingress.ps1"

PS1 = r'''<#
.SYNOPSIS
    给 cloudflared 隧道安全地增加一条 ingress 规则。

.DESCRIPTION
    自动定位 config.yml、备份、去重、插到兜底条目之前、校验并写回。
    任何一步失败都回滚，不会留下坏配置。

    为什么不用手工改：YAML 对 Tab 零容忍，兜底条目的顺序错了隧道直接起不来，
    连带同隧道的其它域名（如 kanban）一起挂掉。

.PARAMETER Hostname
    要新增的域名，如 daily.forestkopa.top

.PARAMETER Port
    该域名转发到的本地端口，如 5190

.PARAMETER ConfigPath
    手动指定 config.yml 路径（默认自动探测）

.PARAMETER WhatIf
    只打印将要做的改动，不实际写入

.EXAMPLE
    .\add-ingress.ps1 -Hostname daily.forestkopa.top -Port 5190

.EXAMPLE
    .\add-ingress.ps1 -Hostname daily.forestkopa.top -Port 5190 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$Hostname,

    [Parameter(Mandatory = $true)]
    [int]$Port,

    [string]$ConfigPath = "",

    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "[v] $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "[!] $m" -ForegroundColor Yellow }
function Fail ($m) { Write-Host "[x] $m" -ForegroundColor Red }
function Step ($m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }

Say "=============================================================="
Say "  cloudflared ingress 添加工具"
Say "=============================================================="
Say "  域名: $Hostname"
Say "  端口: $Port"

# ---------------------------------------------------------------- 1. 定位 config.yml
Step "1/6 定位 config.yml"

$candidates = @()
if ($ConfigPath) {
    $candidates += $ConfigPath
} else {
    $candidates += (Join-Path $env:USERPROFILE ".cloudflared\config.yml")
    $candidates += "C:\Windows\System32\config\systemprofile\.cloudflared\config.yml"
    $candidates += "$env:ProgramData\cloudflared\config.yml"
    # 从服务启动参数里挖 --config
    try {
        Get-CimInstance Win32_Service |
            Where-Object { $_.Name -like '*cloudflared*' -or $_.DisplayName -like '*cloudflared*' } |
            ForEach-Object {
                if ($_.PathName -match '--config\s+"?([^"]+\.yml)"?') {
                    $candidates += $Matches[1]
                }
            }
    } catch { }
}

$cfg = $null
foreach ($c in $candidates) {
    if ($c -and (Test-Path $c)) { $cfg = (Resolve-Path $c).Path; break }
}

if (-not $cfg) {
    Fail "没找到 config.yml。请用 -ConfigPath 手动指定。"
    Say "  已探测过的路径："
    $candidates | Select-Object -Unique | ForEach-Object { Say "    $_" }
    exit 1
}
Ok "配置文件: $cfg"

# ---------------------------------------------------------------- 2. 判断隧道类型
Step "2/6 检查隧道类型"

$raw = Get-Content $cfg -Raw -Encoding UTF8

if ($raw -notmatch '(?m)^\s*ingress\s*:') {
    Warn "配置里没有 ingress 段 —— 这可能是 Quick Tunnel（--url 方式），不是命名隧道。"
    Say ""
    Say "  Quick Tunnel 没有固定域名，无法直接加 ingress。"
    Say "  需要先建命名隧道，见《Cloudflare_操作清单.md》的方案 B。"
    exit 2
}
Ok "发现 ingress 段，是命名隧道"

# ---------------------------------------------------------------- 3. 去重
Step "3/6 检查是否已存在"

if ($raw -match "(?m)^\s*-\s*hostname\s*:\s*$([regex]::Escape($Hostname))\s*$") {
    Warn "$Hostname 已经配置过了，无需重复添加。"
    Say ""
    Say "  当前 ingress 段："
    ($raw -split "`n" | Select-String -Pattern 'hostname|service|^\s*ingress' -Context 0,0) |
        ForEach-Object { Say "    $($_.Line.TrimEnd())" }
    exit 0
}
Ok "$Hostname 尚未配置，继续"

# ---------------------------------------------------------------- 4. 备份
Step "4/6 备份"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bak = "$cfg.bak-$stamp"

if ($WhatIfPreference) {
    Say "  (-WhatIf 干跑，跳过备份与实际写入)"
} else {
    # 注意：用 -WhatIf:$false 显式覆盖，否则 -WhatIf 会传播到 Copy-Item 导致备份缺失，
    # 后面的 Get-Item $bak 就会抛 PathNotFound。
    Copy-Item $cfg $bak -Force -WhatIf:$false
    if (-not (Test-Path $bak)) {
        Fail "备份未生成，中止（原文件未改动）。"
        exit 1
    }
    if ((Get-Item $bak).Length -eq 0) {
        Fail "备份文件为空，中止（原文件未改动）。"
        Remove-Item $bak -Force -WhatIf:$false -ErrorAction SilentlyContinue
        exit 1
    }
    Ok "已备份: $bak"
}

# ---------------------------------------------------------------- 5. 生成新内容
Step "5/6 生成新配置"

$lines = $raw -split "`r?`n"

# 找到 ingress: 行号
$ingressIdx = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*ingress\s*:') { $ingressIdx = $i; break }
}

# 收集 ingress 段的条目行（形如 "  - hostname:" 或 "  - service:"）
$entryIdxs = @()
for ($i = $ingressIdx + 1; $i -lt $lines.Count; $i++) {
    $l = $lines[$i]
    # 遇到顶层键（非缩进）就说明 ingress 段结束
    if ($l -match '^\S' -and $l.Trim() -ne '') { break }
    if ($l -match '^\s*-\s') { $entryIdxs += $i }
}

if ($entryIdxs.Count -eq 0) {
    Fail "ingress 段里没找到任何条目，格式可能不标准。请手工处理，或检查 $cfg"
    exit 1
}

# 找兜底条目：最后一条 "- " 后面不跟 hostname 的
$fallbackIdx = -1
for ($k = $entryIdxs.Count - 1; $k -ge 0; $k--) {
    if ($lines[$entryIdxs[$k]] -notmatch 'hostname\s*:') { $fallbackIdx = $entryIdxs[$k]; break }
}

if ($fallbackIdx -lt 0) {
    Warn "没找到兜底条目（无 hostname 的那条）。"
    Say "  兜底条目是隧道能正常工作的前提，缺失说明配置本身有问题。"
    Say "  为安全起见，本次不自动修改。请先修好配置再重试。"
    exit 1
}
Ok "兜底条目在第 $($fallbackIdx + 1) 行，新规则将插在它前面"

# 检测缩进风格（照抄现有条目）
$indent = "  "
if ($lines[$entryIdxs[0]] -match '^(\s*)-\s') { $indent = $Matches[1] }

$newLines = @()
$newLines += $lines[0..($fallbackIdx - 1)]
$newLines += "$indent- hostname: $Hostname"
$newLines += "$indent  service: http://localhost:$Port"
$newLines += $lines[$fallbackIdx..($lines.Count - 1)]

$newRaw = ($newLines -join "`r`n")
if (-not $newRaw.EndsWith("`r`n")) { $newRaw += "`r`n" }

Say ""
Say "  将要插入的内容（插在第 $($fallbackIdx + 1) 行之前）："
Say "    $indent- hostname: $Hostname"
Say "    $indent  service: http://localhost:$Port"

if ($WhatIfPreference) {
    Say ""
    Warn "-WhatIf 干跑结束，未写入任何文件。"
    Say "  去掉 -WhatIf 即可实际生效。"
    exit 0
}

# 写入前校验：Tab 检查
if ($newRaw -match "`t") {
    Fail "生成的内容里含 Tab 字符，YAML 不接受。中止（原文件未改动）。"
    exit 1
}

# 原子写回：先写临时文件再替换
$tmp = "$cfg.tmp-$stamp"
[System.IO.File]::WriteAllText($tmp, $newRaw, (New-Object System.Text.UTF8Encoding($false)))

# ---------------------------------------------------------------- 6. 校验并落盘
Step "6/6 校验并生效"

function Test-Yaml {
    param([string]$Path)
    $text = Get-Content $Path -Raw -Encoding UTF8
    $errs = @()
    if ($text -notmatch '(?m)^\s*ingress\s*:') { $errs += "没有 ingress 段" }
    if ($text -notmatch '(?m)^\s*-\s*hostname\s*:') { $errs += "ingress 里没有 hostname 条目" }
    if ($text -notmatch "(?m)^\s*-\s*hostname\s*:\s*$([regex]::Escape($Hostname))\s*$") {
        $errs += "新域名没写进去"
    }
    if ($text -match "`t") { $errs += "含 Tab 字符" }
    # 兜底条目必须存在且是最后一条
    $ls = $text -split "`r?`n"
    $idx = -1
    for ($i = 0; $i -lt $ls.Count; $i++) { if ($ls[$i] -match '^\s*ingress\s*:') { $idx = $i; break } }
    $entries = @()
    for ($i = $idx + 1; $i -lt $ls.Count; $i++) {
        if ($ls[$i] -match '^\S' -and $ls[$i].Trim() -ne '') { break }
        if ($ls[$i] -match '^\s*-\s') { $entries += $ls[$i] }
    }
    if ($entries.Count -gt 0) {
        if ($entries[-1] -match 'hostname\s*:') { $errs += "最后一条不是兜底条目（隧道会起不来）" }
    } else {
        $errs += "ingress 段没有条目"
    }
    return $errs
}

$errs = Test-Yaml $tmp
if ($errs.Count -gt 0) {
    Fail "新配置校验未通过："
    $errs | ForEach-Object { Say "    - $_" }
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    Say ""
    Warn "已中止，原文件未被改动。备份: $bak"
    exit 1
}
Ok "新配置校验通过"

Copy-Item $tmp $cfg -Force
Remove-Item $tmp -Force -ErrorAction SilentlyContinue
Ok "已写入: $cfg"

Say ""
Say "  新的 ingress 段："
$final = Get-Content $cfg -Raw -Encoding UTF8
$fl = $final -split "`r?`n"
$fi = -1
for ($i = 0; $i -lt $fl.Count; $i++) { if ($fl[$i] -match '^\s*ingress\s*:') { $fi = $i; break } }
for ($i = $fi; $i -lt $fl.Count; $i++) {
    if ($i -gt $fi -and $fl[$i] -match '^\S' -and $fl[$i].Trim() -ne '') { break }
    Say "    $($fl[$i].TrimEnd())"
}

# ---------------------------------------------------------------- 重启隧道
Say ""
if ($NoRestart) {
    Warn "已指定 -NoRestart，请手动重启隧道使配置生效。"
} else {
    $svc = Get-Service | Where-Object {
        ($_.Name -like '*cloudflared*' -or $_.DisplayName -like '*cloudflared*') -and $_.Status -eq 'Running'
    } | Select-Object -First 1

    if ($svc) {
        Say "  即将重启隧道服务: $($svc.Name)"
        Warn "  ⚠ 同隧道所有域名会闪断 3~5 秒（包括 kanban）"
        Say ""
        $ans = Read-Host "  现在重启吗？(y/N)"
        if ($ans -eq 'y' -or $ans -eq 'Y') {
            try {
                Restart-Service $svc.Name -Force -ErrorAction Stop
                Start-Sleep -Seconds 4
                $st = (Get-Service $svc.Name).Status
                Ok "服务已重启，当前状态: $st"
            } catch {
                Warn "Restart-Service 失败: $($_.Exception.Message)"
                Say "  改用 taskkill（服务会自动重新拉起）："
                Say "    taskkill /F /IM cloudflared.exe"
            }
        } else {
            Warn "已跳过重启。配置已写好，但需要重启隧道才生效。"
        }
    } else {
        Warn "没找到正在运行的 cloudflared 服务，请手动重启。"
    }
}

Say ""
Say "=============================================================="
Ok "完成"
Say "=============================================================="
Say ""
Say "  接下来还要做一步（只能手工，Cloudflare 后台）："
Say "    给 $Hostname 加一条 CNAME 指向隧道"
Say "    - Type: CNAME"
Say "    - Name: $($Hostname.Split('.')[0])"
Say "    - Target: <隧道UUID>.cfargotunnel.com   ← 照抄 kanban 那条的 Target"
Say "    - Proxy: 开启（橙色云朵）"
Say ""
Say "  回滚方法（如需）："
Say "      Copy-Item `"$bak`" `"$cfg`" -Force"
Say ""
'''

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_bytes(b'\xef\xbb\xbf' + PS1.encode('utf-8'))
print(f'已生成: {OUT}')
print(f'  体积: {OUT.stat().st_size:,} B')
raw = OUT.read_bytes()
print(f'  BOM : {raw[:3] == b"\xef\xbb\xbf"}')
print(f'  Tab : {"有（需检查）" if b"\t" in raw else "无"}')
