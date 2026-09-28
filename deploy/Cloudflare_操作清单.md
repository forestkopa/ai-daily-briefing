# Cloudflare 侧操作清单（首次部署做一次，之后永不再动）

> 这份文件解决一件事：**上线 `daily.forestkopa.top` 时，Cloudflare 那边到底要动什么。**
> 全程**只在首次部署做一次**。以后改代码用增量包更新，不需要再看这份文件。

---

## 先确认你的隧道是哪种（30 秒）

打开服务器上的 PowerShell：

```powershell
Get-Service | Where-Object Name -like '*cloudflared*'
```

拿到服务名后，看它的启动参数：

```powershell
# 把 <服务名> 换成上面查到的
Get-CimInstance Win32_Service -Filter "Name='<服务名>'" | Select-Object -ExpandProperty PathName
```

根据输出判断：

| 输出里有什么 | 说明 | 要做什么 |
|---|---|---|
| `tunnel run <名字或UUID>` 或 `--config` | **命名隧道** | 走下面【方案 A】，ingress + CNAME 都要做 |
| `--url http://localhost:xxxx` | **Quick Tunnel** | 走下面【方案 B】，先把命名隧道建起来 |
| 什么都没有 / 服务不存在 | 还没装 | 先装 cloudflared 并建隧道 |

> kanban 现在能通过 `kanban.forestkopa.top` 访问，说明**大概率是命名隧道**。
> 但请实际跑一下上面的命令确认 —— 只有输出里出现 `tunnel run` 才是。

---

## ⚠️ 如果你是在 Zero Trust 后台加的 Public Hostname（不是改 config.yml）

**这是另一套机制，和上面的【方案 A】二选一，千万别两边都配。**

路径：Zero Trust 控制台 → Networks → Tunnels → 选隧道 → **Public Hostname** → Add a public hostname。

在这个界面里，**最容易错的就是 Protocol 那一栏**：

| 字段 | 正确填法 | 常见错误 |
|---|---|---|
| Subdomain | `daily` | |
| Domain | `forestkopa.top` | |
| Path | 留空 | |
| **Type** | **`HTTP`** | 填成 `HTTPS` ← **就是这个错** |
| **URL** | **`localhost:5190`** | 写成 `https://localhost:5190` |

> 🔴 **关键：Type 必须选 `HTTP`，不能选 `HTTPS`。**
>
> 我们的 `server.js` 是**纯 HTTP 服务**（源码里是 `require('http')` + `http.createServer`，
> 没有 TLS、没有证书）。如果 Cloudflare 按 `https://` 去连后端，
> 它会尝试 TLS 握手，而对方只会回明文 HTTP —— **握手必然失败，页面就是 502**。
>
> 正确写法（两种等价，任选其一）：
> - Type = `HTTP`，URL = `localhost:5190`
> - Type = `HTTPS` 时 URL 必须显式写 `http://localhost:5190` —— **不推荐**，容易混淆
>
> **记住一条：Type 和 URL 的协议要一致，且必须匹配后端的真实协议。**
> 后端是明文 HTTP ⇒ 这里就得是 `http://`。

改完点 **Save hostname**，等待约 10~30 秒生效，然后直接访问 `https://daily.forestkopa.top`。

> 注意：**浏览器访问公网用 `https://` 是对的**（Cloudflare 边缘有证书）；
> 但**Cloudflare 回源到 `localhost:5190` 必须用 `http://`**。这两件事经常被混淆 ——
> 前者是"外面看到的"，后者是"里面连的"。

---

## 【方案 A】命名隧道：加一条 ingress + 一条 CNAME

### A-1 找到配置文件

```powershell
# Windows 上 config.yml 通常在这两个位置之一
Test-Path "$env:USERPROFILE\.cloudflared\config.yml"
Test-Path "C:\Windows\System32\config\systemprofile\.cloudflared\config.yml"
```

> 如果服务是以 SYSTEM 身份跑的，配置文件在**第二个路径**。
> 两个都存在的话，用上面 `PathName` 输出里 `--config` 指的那个。

看一下当前内容：

```powershell
Get-Content "<上面确认的路径>"
```

应该长这样（关键是 `ingress` 列表）：

```yaml
tunnel: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
credentials-file: C:/Users/Administrator/.cloudflared/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.json

ingress:
  - hostname: kanban.forestkopa.top
    service: http://localhost:5181
  - service: http://localhost:5181        # ← 兜底条目，无 hostname，必须在最后
```

### A-2 加两条（就在兜底条目之前）

**改之前先备份**：

```powershell
Copy-Item "<config.yml 路径>" "<config.yml 路径>.bak"
```

把 ingress 列表改成这样 —— **新增的两行插在兜底条目的前面**：

```yaml
ingress:
  - hostname: kanban.forestkopa.top
    service: http://localhost:5181
  - hostname: daily.forestkopa.top        # ← 新增
    service: http://localhost:5190        # ← 新增
  - service: http://localhost:5181        # ← 兜底，必须保持最后
```

**三条缩进铁律**（错一个隧道就起不来）：

1. **用空格，不要用 Tab** —— YAML 对 Tab 零容忍
2. `- hostname:` 前面是 **2 个空格**，`service:` 与 `hostname:` **左对齐**（也多 2 个空格）
3. 兜底条目（没有 `hostname` 的那条）**必须在最后**，且**不能删**

> ⚠️ **有没有省事的办法？** 有。**用 `add-ingress.ps1` 自动改**：
> 它会备份、检查是否已存在、自动插到兜底前、并校验 YAML 合法性，改坏了自动回滚。
> 如果你不想手工碰 YAML，告诉我，我给你生成这个脚本。

### A-3 重启隧道

```powershell
# 把 <服务名> 换成第一步查到的
Restart-Service <服务名>
```

或者（如果 `Restart-Service` 被策略拒绝）：

```powershell
taskkill /F /IM cloudflared.exe
# 服务会自动重启它
```

> ⚠️ **重启瞬间，同隧道所有域名都会闪断 3~5 秒**，包括正在跑的 kanban。
> **避开业务高峰再动手。** 这是唯一会影响到已有服务的一步。

验证隧道起来了：

```powershell
Get-Service <服务名>
# Status 应该是 Running
```

### A-4 在 Cloudflare 后台加 CNAME

浏览器打开 Cloudflare 控制台 → 选中 `forestkopa.top` → 左侧 **DNS** → **Records** → **Add record**：

| 字段 | 填什么 |
|---|---|
| Type | `CNAME` |
| Name | `daily` |
| Target | `<隧道UUID>.cfargotunnel.com` |
| Proxy status | **Proxied（橙色云朵）** ← 必须开 |
| TTL | Auto |

**隧道 UUID 从哪来**：就是 `config.yml` 里 `tunnel:` 那行的值。

> **最稳的办法**：直接照抄 `kanban` 那条记录的 Target，只把 Name 从 `kanban` 改成 `daily`。
> 因为两条走的是同一条隧道，Target 必然相同。

**顺手确认一下 SSL 模式**：左侧 **SSL/TLS** → **Overview** → 加密模式应该是
**Full** 或 **Full (strict)**，不要用 Flexible。

---

## 【方案 B】Quick Tunnel：先建命名隧道

如果 A-1 查出你的隧道是 `--url http://localhost:xxxx` 这种 Quick Tunnel，
那它**没有固定域名**，每次重启换个随机地址。要托到 `daily.forestkopa.top` 必须先建命名隧道：

```powershell
# 1) 登录（会弹浏览器，选 forestkopa.top 这个 Zone）
cloudflared tunnel login

# 2) 建隧道，记下输出的 UUID
cloudflared tunnel create daily-briefing

# 3) 建 config.yml（内容照【方案 A】A-1 的样式写）
#    tunnel: 填刚生成的 UUID
#    credentials-file: 指向 ~/.cloudflared/<UUID>.json

# 4) 加 DNS 记录（cloudflared 会自动帮你建 CNAME，比手工加稳）
cloudflared tunnel route dns daily-briefing daily.forestkopa.top

# 5) 注册成 Windows 服务
cloudflared service install
```

之后回到【方案 A】的 A-3 验证。

---

## 更新时要不要碰 Cloudflare？

**完全不用。**

| 场景 | 要动 Cloudflare 吗 |
|---|---|
| 改页面样式 / 加信源 / 改取数逻辑 | ❌ 不用 |
| 换 server.js | ❌ 不用 |
| 换域名 | ✅ 要（ingress + CNAME 各改一次） |
| 换服务器机器 | ✅ 要（重新建隧道或改 target） |
| 换端口 | ✅ 要（改 ingress 里的 service 端口） |

> 一句话：**只要域名和端口不变，Cloudflare 配一次就够了，以后改代码永远不用回来。**

---

## 快速自检清单（首次部署）

```
[ ] 确认隧道类型（tunnel run = 命名隧道）
[ ] 备份 config.yml
[ ] ingress 加两条，位置在兜底条目之前
[ ] 缩进全用空格，service 与 hostname 对齐
[ ] 兜底条目仍在最后
[ ] 避开高峰，重启隧道
[ ] 隧道服务 Status = Running
[ ] Cloudflare 后台加 CNAME：daily → <UUID>.cfargotunnel.com，橙云开启
[ ] SSL/TLS 模式 = Full 或 Full (strict)
[ ] 本机验证：curl.exe http://127.0.0.1:5190/healthz  → 200
[ ] 公网验证：打开 https://daily.forestkopa.top
```
