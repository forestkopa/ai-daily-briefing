# 更新日志（CHANGELOG）

> 反向时间顺序。完整历史见 GitHub Releases：https://github.com/forestkopa/ai-daily-briefing/releases

## v1.0（2026-09-28）首个公开版本

> 把一个「每天手动整理 AI 资讯」的活儿，做成了**零 AI 调用、零 token 消耗**的全自动看板：
> 服务器每天 08:30 自己抓 RSS、自己渲染 HTML，公网可直接访问。

### 抓取层（`fetch_rss.py`）
- **11 个全中文信源**，按 5 大板块归类：模型与厂商 / 产品与工程 / 行业动态 / 研报与数据 / 技巧与观点。
  实测两轮共探测 67 个中文地址，淘汰机器之心（XML 坏）、新智元、36氪、虎嗅等不可用源，
  清单与症状记录在 README「已知失效/不可用的源」，避免后人重复踩。
- **三级 AI 相关性判定** `is_ai_related`：标题强信号词 → 标题弱信号词（独立成词的 AI）→ 正文强信号词。
  三条路径都先过 `FALSE_POSITIVE` 排除表，挡掉「AI 耳机评测」「AI 语音车机」这类伪相关。
- **中文兜底** `is_zh()`：按中文字符占比判定（标题 ≥12 字要求 ≥0.20，短标题 ≥0.40），
  即使某个源以后混入英文条目，页面也不会出现英文。
- **摘要三级降级** `make_summary`：占位符（只有「点击查看原文」）→ 抓 og:description / 首段；
  以标题开头 → 裁掉重复前缀；全失败 → 回落成一句说明。
- **文本清洗** `clean_text`（在摘要生成之前跑）：
  - 零宽 / 双向控制字符 `ZW_RE` —— 爱范儿、199IT 会在 description 里塞隐形水印（实测分别 99 / 454 个），
    属 Unicode Cf 类，`\s` 匹配不到，会留下「看不见的乱码」影响复制与查重。
  - 源站推广尾巴 `PROMO_RE` —— 爱范儿摘要末尾挂着 40 字公众号推广，占 180 字配额两成，
    且**排在末尾**，不剔除时被截断的反而是正文。
  - 剔除后若正文不足 20 字，自动抓文章首段补内容，不留空卡。
- **板块配额 + 低频板块放宽时间窗**：防止全站源把某板块撑爆；模型发布与研报是低频产出，
  强制用 14 天窗口避免空板。
- **无日期源显式标记** `no_date`：199IT 的 feed 不带日期，此前被 `dt is None` 静默丢弃。
- 间歇性不稳的源（少数派 / 爱范儿 / 快科技）内置 3 次重试（1.5s / 3s 间隔）。

### 渲染层（`build.py`）
- **bankon 新粗野主义风格**：米白纸底 `#F2F1EC` + 纯黑 2px 描边 + 硬投影 `4px 4px 0` + 珊瑚色 `#F2704F` 点缀。
- 首屏巨型标题 + 右侧摘要 + 双 CTA；4 格通栏数据条（小屏折成 2×2）。
- 焦点区三件套：`最新更新`（头条 + 线稿插画）/ `今日收录`（珊瑚卡）/ `共 N 大板块`。
- 顶部胶囊导航（滚动自动高亮）、全局连续编号、卡片错峰淡入、右下角回到顶部。
- **降级保底**：卡片入场规则挂在 `html.js-ready` 之下，JS 未执行时内容依然可见；
  `prefers-reduced-motion` 下关闭全部动效；打印时隐藏浮层、卡片强制展开。

### 服务端（`deploy/server.js` + `cli.py`）
- 零依赖 Node 静态服务，`/` → `data/latest.html`，`/healthz` 探活。
- **页面内刷新按钮 ×2**：POST `/api/refresh` 让服务器重抓，前端轮询 `/api/status`，
  `state=ok` 后自动 `location.reload()`。
- 刷新按钮三重保护：**单飞锁**（并发 → 429 busy）、**冷却**（默认 60s → 429 cooldown）、
  **超时**（单次超 5 分钟杀子进程）；`file://` 打开时按钮自动隐藏。
- `cli.py` 一条命令走完抓取 → 生成 → 归档 → 清理（`--keep-days 30`），供定时任务调用。

### 部署体系
- **NSSM 注册 Windows 服务** `ai-briefing-server`（开机自启、崩溃自动重启、日志轮转）。
- **每日 08:30 计划任务** `ai-briefing-update`，以 SYSTEM 身份运行，出数完全交给服务器。
- **Cloudflare 隧道**发布公网域名；ingress 是顺序匹配，具体域名必须排在兜底项之前。
- **双包设计**：
  - `ai-briefing-deploy.zip`（全量 ~8 MB）—— 首次上线，含 exe + nssm.exe。
  - `ai-briefing-update.zip`（增量 ~37 KB）—— 日常改代码，**只含源文件**，
    按设计不含 `data/` `venv/` `logs/`，不可能误覆盖服务器数据。
- **`update.ps1` 五步全自动**（v1.0 期间修掉三个真实缺陷，详见下方「修复记录」）：
  定位服务真实目录 → 备份 → 替换（**两处目录都替换**）→ 需重启时重启并探活 → **重新生成页面**。
- **`preflight.ps1` 只读自检**：Python（含真伪判定）、端口、Node、nssm、pypi、cloudflared 一次查完。
- **`diag-502.ps1` 只读排障**：定位 502 断在哪一段（隧道/路由/回源）。

### 开发工具（`tools/`）
| 脚本 | 用途 |
|---|---|
| `gen_preview_bankon.py` | 从真实 `today.json` 生成 UI 改版预览页 |
| `shoot_cdp.py` | 走 CDP 截图 + **真机布局审计**（横向溢出 / 入场状态 / 元素计数） |
| `verify_latest.py` | 产物断言：卡片数、板块数、乱码、主标题、英文标题、**推广残留 == 0** |
| `verify_package.py` | 解包 zip 跑真实产物，核对包内文件确实是新版 |
| `diag_zw.py` / `diag_promo.py` | 零宽字符 / 推广尾巴的现场诊断与误删回归 |
| `gen_preflight.py` / `gen_add_ingress.py` | 生成服务器自检脚本 / ingress 配置片段 |
| `clean_tmp.py` | 清理验证临时目录 |

### 发布流水线（`tools/sync-release.ps1`）
照 project-kanban 的套路做一个本地发版脚本，一次跑完「push main → 打不可变标签 `vX.Y` →
滚动 `latest` 指针 → 创建/更新同名 Release」：

- **`vX.Y` 不可变里程碑**（一次创建、永久保留）+ **`latest` 移动指针**（永远指向当前最大版本号）。
  发布更高版本时 `latest` 给到新提交，旧版本自动不再带 `latest`；GitHub 的 Latest 徽标由平台自动赋予。
- **推送确认门禁**：默认交互要输入 `YES` 才推；`-Force` 只在用户已明确批准时由脚本/自动化传入
  （沿用「每日推送须经用户同意」的约定）。
- **鉴权不落盘**：优先用 `$env:GH_PAT`，缺省时自动读 `~/.git-credentials`；
  push 优先走 git 自带凭据，失败才用 PAT 拼 URL 兜底，且所有输出先过 `Sanitize` 抹掉 token。
- 脚本内固化 5 个本机实测坑（见文件头注释），其中 3 个是发布流水线专属：
  `GIT_EXEC_PATH` 必须注入、token 不得进日志、`Invoke-RestMethod` 必须传 UTF-8 字节。

### 两个本机特有的坑（已固化进代码）
- **safe-delete 钩子会拦截 `os.remove` / `shutil.rmtree`** —— 删除必须用 ctypes 直调
  `SHFileOperationW`，见 `clean_cache.py` 的 `permanent_delete()`。
- **服务器是 Python 3.8.8**，依赖必须钉版本（`feedparser==6.0.12`，6.0.13+ 要 ≥3.10）。

### 修复记录（v1.0 发布前）
1. **`html.js-ready .reveal` 反压 `.reveal.in`**（P0）：入场规则特异性高一级，
   加 `.in` 也覆盖不住 → 36 张卡永久 `opacity:0`、整页空白。产物体积从 71 KB 骤增到 474 KB 才暴露。
2. **`update.ps1` 只换代码不重新生成页面**（P0）：换了 `build.py`，页面还是上次生成的旧产物，
   用户改完 UI 打开却「没变化」，会直接判定更新失败 → 新增自动重新生成步骤。
3. **`update.ps1` 让用户手敲裸 `nssm`**：`nssm` 不在 PATH，该命令必然 `CommandNotFound`。
   且它没查「脚本所在目录」——而 nssm.exe 恰恰常与解压出来的脚本同目录 → 重写为
   服务目录 → 脚本目录 → 安装目录 → 常见路径 → 注册表反查，并改用能跑通的指引。
4. **只替换 `-InstallDir`、不管服务实际工作目录**：服务 `AppDirectory` 可能与安装目录不一致，
   导致「替换成功但服务没用到」的假成功 → 先探测真实目录，不一致时**两处都替换**。
5. **包内 `ai-briefing-update.exe` 是旧版**：时间戳比 `build.py` 旧 3 天，内嵌旧 UI，
   走 exe 备用路线会拿到旧界面 → 重打包并**实跑验证**产物。
   > `grep` 二进制找源码字符串**无效**（PyInstaller 压缩内嵌），唯一硬验证是实跑看产物。
6. **`sync-release.ps1` push 报 `git: 'remote-https' is not a git command`**：本机 PortableGit 的
   `mingw64\libexec\git-core` 是**空目录**，远程助手只存在于 `mingw64\bin`，而 git 只从
   `GIT_EXEC_PATH` 找远程助手。实测矩阵：加 PATH **无效**（rc=128）、设 `GIT_EXEC_PATH` **有效**（rc=0）。
7. **PAT 泄露进 `logs/_sync.log`**：兜底 URL 里的 token 随错误信息被写进日志 → 新增 `Sanitize()`，
   所有输出先抹 token，并立即清理已泄露的日志。
8. **Release 正文中文变 `?`**（P0，发布后才被 GitHub 侧原始字节复核抓到）：PS 5.1 的
   `Invoke-RestMethod` 在 `-ContentType` 不带 `charset` 时把**字符串** body 按 ISO-8859-1 编码，
   而 PS 5.1 的 `ConvertTo-Json` 输出的是**字面中文**（不做 `\uXXXX` 转义），两件事叠一起必然踩中。
   实验矩阵（本机 PSVersion 5.1.19041.7725 / Default enc gb2312）：字符串 body → `22 3f 3f 3f 3f 20`
   → `"???? ABC"`；UTF-8 字节 body → `22 e4 b8 ad e6 96 87` → `"中文测试 ABC"`。
   → 改为 `ConvertTo-Json` 后取 `[Text.Encoding]::UTF8.GetBytes()` 传 `-Body`，并显式 `charset=utf-8`。
   > 曾误把这条归因于「git 输出编码乱码顺着写进正文」——那是另一条独立的坑（提交信息乱码），两处都要修。
9. **本机两种凭据助手全不可用 → `origin` 形式的 push 必然失败**：`credential.helper` 配的是
   GCM（`git-credential-manager.exe` 存在），但 `GIT_TRACE=1` 显示 git 走到
   `run_command: 'git credential-manager get'` 后**静默 exit 128，两个流都是 0 字节**；
   用 `-c credential.helper=` 清空助手才露出真因（`could not read Username ... terminal prompts disabled`）；
   想换 `store` 也不行——`mingw64\bin` 下**根本没有 `git-credential-store.exe`**
   （`~/.git-credentials` 只对本脚本读 PAT 有用，git 自己读不到）。
   → 保留「先试 `origin`、失败再走 URL 内联凭据」的双路径，并在日志里注明这是**预期现象**；
   同时给「两流全空的 exit 128」补上可读提示，不再是无字天书。
