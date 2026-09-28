# tools/sync-release.ps1
# 用法（powershell）：
#   .\tools\sync-release.ps1                       # 仅推送 main（普通 push，不改版本/标签）
#   .\tools\sync-release.ps1 -Version v1.1         # 发版：打不可变版本号 v1.1 + 把 latest 标签滚动到该提交
#   .\tools\sync-release.ps1 -Force                # 跳过交互确认（仅当用户已明确批准推送时使用）
#
# 鉴权：无需手动设 GH_PAT。脚本优先用 $env:GH_PAT，缺省时自动读取
#       ~/.git-credentials（credential.helper=store 已缓存的 PAT）；push 走 git 自带凭据，最稳。
#
# 版本约定（沿用 project-kanban，2026-08-25 确定）：
#   - latest 标签 = 移动指针，始终指向「当前最大版本号」对应的提交。
#     发布更高版本后，latest 移动到新提交，旧版本即不再带 latest。
#   - vX.Y 标签 = 不可变里程碑（一次创建、永久保留），对应同名 GitHub Release。
#   - GitHub 的 "Latest" 徽标由 GitHub 自动赋予「最新发布的 release」，无需手动管理。
#
# 本机实测踩过的七个坑（2026-09-28 修复，勿回退）：
#   1) 【致命】push 报 "git: 'remote-https' is not a git command"。
#      本机 PortableGit 的 mingw64\libexec\git-core 是【空目录】，远程助手
#      git-remote-https.exe 只存在于 mingw64\bin；而 git 是从 GIT_EXEC_PATH
#      里找远程助手的。实测：把 mingw64\bin 加进 PATH 完全无效（rc=128），
#      把 GIT_EXEC_PATH 指过去才 rc=0。
#      -> 探测含 git-remote-https.exe 的目录，注入子进程 GIT_EXEC_PATH。
#   2) 【安全】PAT 兜底 URL 里的 token 会随错误信息写进日志 -> 必须 Sanitize 后再输出。
#   3) 【逻辑】原版把 Log 调用写在 function Log 定义之前，未取到 PAT 时会报
#      "无法将 Log 识别为 cmdlet" -> 函数定义必须前置于首次调用。
#   4) 【乱码A】git 输出是 UTF-8，中文 Windows 的 [Console]::OutputEncoding 是 GBK，
#      不显式改成 UTF-8，`git log -1 --pretty=%s` 取回的提交信息会变乱码
#      （实测 "v1.0：AI 日报看板..." -> "v1.0锛欰I 鏃ユ姤鐪嬫澘..."）。
#      -> 调用 git 前后改回/恢复 OutputEncoding。
#      【勘误】曾误以为它「顺着写进 Release 正文」——经 GitHub 侧原始字节复核，
#      Release 正文变 '?' 是坑 5 的独立原因，与本条无关，两处都要修。
#   5) 【乱码B，Release 正文变 '?' 的真因】PS 5.1 的 Invoke-RestMethod 在
#      -ContentType 不带 charset 时，把【字符串】body 按 ISO-8859-1 编码，中文全变 '?'；
#      而 PS 5.1 的 ConvertTo-Json 输出【字面中文】（不转 \uXXXX），必然踩中。
#      -> ConvertTo-Json 后再手工转 UTF-8 字节数组传 -Body + 显式 charset=utf-8。
#      详见主流程第 5 步的注释与实验矩阵。
#   6) 【本机凭据助手全废 -> origin 形式的 push 必失败】。实测矩阵（2026-09-28）：
#        credential.helper = manager + !"...\git-credential-manager.exe"
#        GIT_TRACE=1 显示 git 走到 `run_command: 'git credential-manager get'` 后，
#        整进程静默 exit 128，stdout/stderr 都是 0 字节；
#        改用 -c credential.helper= 清空助手 -> 才报出真正原因
#        "fatal: could not read Username for 'https://github.com': terminal prompts disabled"；
#        而想换 credential.helper=store 也不行：mingw64\bin 下【根本没有
#        git-credential-store.exe】（~/.git-credentials 只对本脚本读 PAT 有用，git 读不到）。
#      => 本机唯一可行通路是【把凭据内联进 remote URL】绕过助手，这不是偷懒，是唯一解。
#         所以下面 Invoke-GitPush 的「先试 origin、失败再走 URL」必须保留，
#         push 日志里那条「走 git 自带凭据失败」在本机是【预期现象】，不是故障。
#      注：URL 里的 token 会短暂出现在本机进程命令行，属可接受残余风险；
#         脚本已用 Sanitize 保证它不落日志，也不进 CI。
#   7) 【逻辑】latest / Release 正文锚定 HEAD 会漂移。打完 vX.Y 之后又往 main 提了修复，
#      下次再跑 -Version vX.Y 时，latest 与 Release 正文里的「基于提交」会指向新的 HEAD，
#      与 vX.Y 标签自身提交不一致（实测 latest 漂到 3377d15，而 v1.0 在 9a6a0a7），
#      违反本文件开头「latest 始终指向当前最大版本号对应的提交」这条约定。
#      -> 标签已存在时用 `git rev-list -n 1 <tag>` 取【标签自己的提交】，
#         再拿它去落 latest、写 Release 正文与提交信息。
param(
    [string]$Version = '',  # 形如 v1.1；为空则只推送 main，不动版本号/latest
    [switch]$Force          # 跳过交互确认（仅当用户已明确批准推送后、由脚本/自动化显式传入）
)

$ErrorActionPreference = 'Continue'

# ------------------------------------------------------------------ 工具函数（必须前置）
function Log($m) {
    $s = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"
    Write-Host $s
    try { Add-Content -Path $script:LogPath -Value $s -Encoding utf8 } catch {}
}

# 任何输出前过一遍：把 PAT 抹掉，避免 token 落进日志/控制台
function Sanitize($s) {
    if (-not $s) { return $s }
    if ($script:Pat) { return ($s -replace [regex]::Escape($script:Pat.Trim()), '***') }
    return $s
}

# ------------------------------------------------------------------ 解析 git
$gitExe = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $gitExe) {
    $candidates = @(
        'C:/Program Files/Git/bin/git.exe',
        'C:/Users/Administrator/.workbuddy/binaries/PortableGit/versions/1.2.0/cmd/git.exe',
        'C:/Users/Administrator/.workbuddy/binaries/PortableGit/versions/1.2.0/mingw64/bin/git.exe'
    )
    foreach ($c in $candidates) { if (Test-Path $c) { $gitExe = $c; break } }
}
if (-not $gitExe) { Write-Error '找不到 git 可执行文件，请确认已安装 Git 并在 PATH 中'; exit 1 }

# 探测 git 的各目录（见文件头坑 1 / 坑 4）
#   - GIT_EXEC_PATH：git 从这里找远程助手 git-remote-https.exe（libexec\git-core 是空的）
#   - PATH：credential.helper 配成 !"<绝对路径>" 时是「shell 命令」，git 要能调到 sh
#     与 helper 本体，都在 mingw64\bin / usr\bin 下
$gitRoot = $null
$g = $gitExe
for ($i = 0; $i -lt 4 -and $g; $i++) {
    $g = Split-Path -Parent $g
    if ($g -and (Test-Path (Join-Path $g 'mingw64'))) { $gitRoot = $g; break }
}

$execDirs = @()
$pathDirs = @()
if ($gitRoot) {
    foreach ($c in @(
            (Join-Path $gitRoot 'mingw64\bin'),
            (Join-Path $gitRoot 'mingw64\libexec\git-core')
        )) {
        if (Test-Path $c) { $execDirs += $c }
    }
    foreach ($c in @(
            (Join-Path $gitRoot 'mingw64\bin'),
            (Join-Path $gitRoot 'usr\bin'),
            (Join-Path $gitRoot 'cmd')
        )) {
        if (Test-Path $c) { $pathDirs += $c }
    }
}
$helperDir = Split-Path -Parent $gitExe
if ((Test-Path (Join-Path $helperDir 'git-remote-https.exe')) -and ($execDirs -notcontains $helperDir)) {
    $execDirs += $helperDir
}
$gitExecPath = ($execDirs | Select-Object -Unique) -join ';'
$gitPathAdd = ($pathDirs | Select-Object -Unique) -join ';'

$repo     = 'forestkopa/ai-daily-briefing'
$repoRoot = Split-Path -Parent $PSScriptRoot   # 项目根目录（tools 的父目录）
$logDir   = Join-Path $repoRoot 'logs'
$script:LogPath = Join-Path $logDir '_sync.log'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }

# ------------------------------------------------------------------ 解析 PAT
# 仅用于 Release API；push 优先走 git 自带凭据（credential helper / store）。
$script:Pat = $env:GH_PAT
if (-not $script:Pat) {
    $storeFile = Join-Path $env:USERPROFILE '.git-credentials'
    if (Test-Path $storeFile) {
        $line = Select-String -Path $storeFile -Pattern 'github\.com' | Select-Object -First 1
        if ($line) {
            $m = [regex]::Match($line.Line, 'https://[^:]+:([^@\r\n]+)@github\.com')
            if ($m.Success) { $script:Pat = $m.Groups[1].Value.Trim() }
        }
    }
}

# ------------------------------------------------------------------ git 调用
function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    # 用临时文件分离 stdout/stderr：
    #   - 避免 PowerShell 把 git 的 stderr（如 "Everything up-to-date"）当 NativeCommandError 喷屏
    #   - 避免混流污染后面要正则提取的 hash / 提交信息
    # 注：不用 ProcessStartInfo（本机实测其 EnvironmentVariables 取值为 null，
    #     赋值时报 "无法对 Null 数组进行索引"）；改为临时改本进程 PATH 后直接调用。
    $oldExec = $env:GIT_EXEC_PATH
    $oldPrompt = $env:GIT_TERMINAL_PROMPT
    $oldPath = $env:PATH
    $oldConsoleOut = [Console]::OutputEncoding
    $tmpO = [System.IO.Path]::GetTempFileName()
    $tmpE = [System.IO.Path]::GetTempFileName()
    try {
        if ($gitExecPath) { $env:GIT_EXEC_PATH = $gitExecPath }   # 让 git 找到 git-remote-https.exe
        if ($gitPathAdd) { $env:PATH = "$gitPathAdd;$oldPath" }   # 让 credential.helper(!shell) 能跑
        $env:GIT_TERMINAL_PROMPT = '0'          # 绝不弹凭据输入
        # 坑 4：git 输出是 UTF-8，而中文 Windows 的 [Console]::OutputEncoding 是 GBK，
        # 不改成 UTF-8 的话，提交信息/分支名里的中文会变成乱码（如 "v1.0锛欰I"）。
        try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
        & $gitExe @GitArgs 1> $tmpO 2> $tmpE
        $rc = $LASTEXITCODE
        $stdout = if (Test-Path $tmpO) { [System.IO.File]::ReadAllText($tmpO) } else { '' }
        $stderr = if (Test-Path $tmpE) { [System.IO.File]::ReadAllText($tmpE) } else { '' }
        if ($rc -ne 0) {
            $detail = (Sanitize $stderr).Trim()
            if (-not $detail) { $detail = (Sanitize $stdout).Trim() }
            if (-not $detail) {
                # 坑 6：本机凭据助手不可用时，git 尝试调 helper 会【静默 exit 128，
                # 且 stdout/stderr 一个字都不输出】，报错信息空着会让人无从下手。
                $detail = '（无任何输出；多为凭据助手不可用所致 —— 见文件头坑 6）'
            }
            throw (Sanitize ("git " + ($GitArgs -join ' ') + " 失败（exit $rc）: $detail"))
        }
        return $stdout
    } finally {
        $env:GIT_EXEC_PATH = $oldExec
        $env:GIT_TERMINAL_PROMPT = $oldPrompt
        $env:PATH = $oldPath
        try { [Console]::OutputEncoding = $oldConsoleOut } catch {}
        Remove-Item $tmpO, $tmpE -Force -ErrorAction SilentlyContinue
    }
}

# git push：优先走 git 自带凭据（store / credential helper），失败再用 PAT 拼 URL 兜底
function Invoke-GitPush {
    param([string]$Ref, [switch]$Force)
    $base = @('push')
    if ($Force) { $base += '-f' }
    $base += 'origin'
    $base += $Ref
    try {
        Invoke-Git @base
    } catch {
        $firstErr = Sanitize $_.Exception.Message
        if (-not $script:Pat) { throw (Sanitize "git push origin $Ref 失败且无可用的 PAT 兜底：$firstErr") }
        # 记下首次失败原因：本机 credential.helper 走不通是常态（见文件头说明），
        # 但万一以后是别的原因（网络/权限），这里能直接看出来。
        Log "  push 走 git 自带凭据失败（$firstErr）；本机凭据助手不可用属预期现象（见文件头坑 6），改用 PAT 兜底 URL"
        $url = "https://$($script:Pat.Trim())@github.com/$repo.git"
        $fb = @('push')
        if ($Force) { $fb += '-f' }
        $fb += $url
        $fb += $Ref
        Invoke-Git @fb
    }
}

$apiHdr = @{
    Accept                 = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
}

# ------------------------------------------------------------------ 主流程
Log "=== sync-release 开始（Version='$Version'）==="
Log "  git: $gitExe"
if ($gitExecPath -like '*mingw64\bin*') {
    Log "  GIT_EXEC_PATH: $gitExecPath"
} else {
    Log "  ⚠ GIT_EXEC_PATH 未指向含 git-remote-https.exe 的目录，push 可能失败: [$gitExecPath]"
}
Log "  PATH 追加: $gitPathAdd"
if (-not $script:Pat) {
    Log '  ⚠ 未找到 GH_PAT（环境变量或 git store），Release 创建将跳过；push 依赖 git 自带凭据'
}

Push-Location $repoRoot
try {
    # 0) 推送前确认门禁（2026-08-25 用户要求：每日推送 GitHub 须先获用户同意）
    if (-not $Force) {
        $scope = if ($Version) { "main + 版本标签 $Version + latest 滚动" } else { 'main' }
        Write-Host ''
        Write-Host "⚠️  即将推送至 GitHub：$scope"
        Write-Host "    仓库：$repo"
        $ans = Read-Host '输入 YES 确认推送（输入其他任意内容则取消）'
        if ($ans -ne 'YES') {
            Log '❌ 用户未确认，已取消推送'
            exit 0
        }
        Log '✅ 用户已确认推送'
    }

    # 1) 推送代码
    Log '> git push origin main'
    Invoke-GitPush -Ref main

    # 2) 取最新提交信息
    $sha = (Invoke-Git rev-parse HEAD).Trim()
    $msg = (Invoke-Git log -1 --pretty=%s).Trim()
    Log "  最新提交 $sha : $msg"

    if ($Version) {
        if ($Version -notmatch '^v\d+\.\d+(\.\d+)?$') { throw "版本号格式应为 vX.Y（如 v1.1），收到: $Version" }

        # 3) 不可变版本标签（已存在则跳过，不覆盖历史里程碑）
        #    【坑 7】latest 与 Release 正文必须锚定【版本标签自己的提交】，不能用 HEAD。
        #    否则「打完 vX.Y 后又往 main 提了修复」再跑一次时，latest / Release 正文会漂到
        #    与 vX.Y 标签不一致的提交上（实测 latest 漂到 3377d15，而 v1.0 在 9a6a0a7），
        #    违反本文件开头「latest 始终指向当前最大版本号对应的提交」这条约定。
        $tagExists = (Invoke-Git tag -l $Version).Trim()
        if (-not $tagExists) {
            Invoke-Git tag $Version $sha
            Log "> git push origin refs/tags/$Version"
            Invoke-GitPush -Ref "refs/tags/$Version"
            Log "✅ 已打不可变标签 $Version ($sha)"
            $verSha = $sha
        } else {
            $verSha = (Invoke-Git rev-list -n 1 $Version).Trim()
            Log "⚠ 标签 $Version 已存在，跳过创建（不可变里程碑不被覆盖）"
            Log "  锚定提交 $verSha（标签自身提交，非 HEAD $sha）"
        }
        $verMsg = if ($verSha -eq $sha) { $msg } else { (Invoke-Git log -1 --pretty=%s $verSha).Trim() }

        # 4) 移动 latest 标签到【该版本标签的提交】（latest = 当前最大版本号对应的提交）
        Invoke-Git tag -f latest $verSha
        Log '> git push -f origin refs/tags/latest'
        Invoke-GitPush -Ref refs/tags/latest -Force
        Log "✅ latest 标签已滚动到 $Version ($verSha)；旧版本不再带 latest"

        # 5) 创建/更新该版本 Release（正文锚定 $verSha，与标签保持一致）
        $verNotes = @"
## 版本 $Version

- 基于提交：$verSha
- 提交信息：$verMsg
- 变更明细：https://github.com/$repo/commits/$verSha

### 本版本主要更新
> 请在本发布页补充相对上一版本的主要变更说明。

> 本版本为不可变里程碑（标签 $Version 恒定指向 $verSha）；latest 标签已滚动到本版本，GitHub 也会将本 release 标为 Latest。
"@
        # 【坑 5，2026-09-28 实测，勿回退】
        #   PS 5.1 的 Invoke-RestMethod 在 -ContentType 不带 charset 时，
        #   会把【字符串】body 按 ISO-8859-1 编码，中文一律退化成 '?'。
        #   而 PS 5.1 的 ConvertTo-Json 输出的是【字面中文】（不做 \uXXXX 转义），
        #   于是 Release 正文实测存成 "## ?? v1.0 / - ????:..."（GitHub 侧原始字节确认）。
        #   实验矩阵（本机 PSVersion 5.1.19041.7725 / Default enc gb2312）：
        #     字符串 body 经 ISO-8859-1 -> 22 3f 3f 3f 3f 20 -> "???? ABC"
        #     UTF8 字节  body           -> 22 e4 b8 ad e6 96 87 -> "中文测试 ABC"
        #   修法：ConvertTo-Json 成字符串后手工转 UTF-8 字节数组再传 -Body，
        #         并显式 charset=utf-8。传 [byte[]] 时 PS 原样发送，不再二次编码。
        $verBodyJson = @{
            tag_name   = $Version
            name       = $Version
            body       = $verNotes
            prerelease = $false
        } | ConvertTo-Json -Compress
        $verBodyBytes = [System.Text.Encoding]::UTF8.GetBytes($verBodyJson)
        $jsonUtf8 = 'application/json; charset=utf-8'
        if ($script:Pat) {
            $relHdr = $apiHdr.Clone()
            $relHdr['Authorization'] = "Bearer $($script:Pat.Trim())"
            try {
                $vrel = Invoke-RestMethod -Headers $relHdr -Uri "https://api.github.com/repos/$repo/releases/tags/$Version" -Method Get
                Invoke-RestMethod -Headers $relHdr -Uri "https://api.github.com/repos/$repo/releases/$($vrel.id)" -Method Patch -Body $verBodyBytes -ContentType $jsonUtf8
                Log "✅ 版本 Release $Version 已更新"
            } catch {
                Invoke-RestMethod -Headers $relHdr -Uri "https://api.github.com/repos/$repo/releases" -Method Post -Body $verBodyBytes -ContentType $jsonUtf8
                Log "✅ 版本 Release $Version 已创建"
            }
        } else {
            Log "⚠ 无可用 token，跳过 GitHub Release $Version 创建（请手动在 GitHub 页面补发）"
        }
    } else {
        Log '（普通 push：未指定 -Version，版本号与 latest 标签保持不变）'
    }

    Log '=== sync-release 完成 ==='
} catch {
    Log "❌ 失败：$(Sanitize $_.Exception.Message)"
    exit 1
} finally {
    Pop-Location
}
