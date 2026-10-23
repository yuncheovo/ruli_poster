# Ruli CMS 站群 · 发文接口与登录机制文档

> 版本：v1.0（2026-10-15）
> 编写依据：源码常量核对 + 真实账号实测取证（共 13 个探测脚本，零写入）。
> 适用范围：控制中心 `center-admin.ruli.com` 账号名下当前可见的 **96 个应用**（过滤「内部系统」后 **94 个站点**）。

---

## 0. 结论速览（先看这里）

| 问题 | 结论 |
|---|---|
| **能不能脱离控制中心单独登录站点？** | **不能。** 站点虽然保留独立登录页，但服务端已统一关闭账号密码登录入口，任何密码登录请求都返回 `{"code":3,"message":"登录入口错误"}`。 |
| **那站点靠什么认证？** | 靠**控制中心下发的 access token**。流程：登录控制中心 → 换站点 token → 用 `GET {站点}/login?token=xxx` 换取站点会话 Cookie。 |
| **发文接口是什么？** | 独立站 / 合作站：`POST /article/form`（JSON）。aicms：不含发文表单，走内容工具接口（见第 5 节）。 |
| **token 有什么特性？** | 有效期约 **60 秒**、**一次性**（用过即失效，不可复用、不可分享）。 |
| **站点分几类？** | 三类：独立推广站（109）、合作站（1，`hz-admin-*`）、aicms 内部系统（1）。前两类**完全同构**，可共用同一套接口。 |

---

## 1. 站点分类与识别规则

控制中心返回的每个应用带有 `url` 字段，据此判定类型：

```python
domain = cms_url.split("://")[1].split("/")[0]      # 例：admin.cengguai.com

is_cooperation = domain.startswith("hz-admin-")                    # 合作站
is_independent = (domain.startswith("admin.") and "ruli.com" not in domain) or is_cooperation
is_aicms       = "ruli.com" in domain and not is_cooperation       # aicms 内部系统
```

| 类型 | 域名特征 | 数量 | 前端形态 | 认证方式 |
|---|---|---|---|---|
| **独立推广站** | `admin.<自定义域名>.com` | 109 | Pear Admin + layui + UEditor-Plus | `SESSID` Cookie |
| **合作站** | `hz-admin-<名称>.ruli.com` | 1（yeekang） | 与独立站**完全同构** | `SESSID` Cookie |
| **aicms** | `aicms-admin.ruli.com` | 1 | Vue SPA（ele-admin-template） | `Authorization: Bearer` |

> ⚠️ **踩坑点**：合作站域名含 `ruli.com`，若按「含 ruli.com 即 aicms」的粗判断会误走 aicms 的 `/site/take-new-token` 接口，而该接口对合作站返回 404，导致登录必然失败。必须先判 `hz-admin-` 前缀。

---

## 2. 控制中心 API（认证入口）

- 管理页：`https://center-admin.ruli.com`
- API 根：`https://center-admin-api.ruli.com`
- **域名规律**：`XXX-admin.ruli.com` → `XXX-admin-api.ruli.com`（即把 `-admin.` 替换为 `-admin-api.`）

### 2.1 登录

```http
POST /login/password-login
Content-Type: application/json

{
  "username": "手机号",
  "password": "明文密码",
  "remember": true
}
```

响应：

```json
{
  "code": 0,
  "message": "恭喜您，登录成功！",
  "data": {
    "token": "32 位十六进制字符串",
    "expire_at": "2026-10-22 17:16:52"
  }
}
```

- 密码**明文传输**，无 AES 加密。
- token 有效期约 **7 天**，之后需重新登录。
- 后续请求统一带 `Authorization: Bearer {token}`。

### 2.2 获取站点列表

```http
GET /site/apps?page=1&limit=200
Authorization: Bearer {token}
```

响应 `data.items[]` 关键字段：

| 字段 | 说明 | 示例 |
|---|---|---|
| `id` | 应用 ID | `9` |
| `name` | 站点名称 | `层乖整形` |
| `signature` | 站点唯一标识（后续换 token 用） | `cengguai` |
| `url` | 站点登录页地址 | `https://admin.cengguai.com/login` |
| `categoryText` | 分类，用于过滤 | `推广站 / 苟浩然`、`内部系统` |
| `ownerText` | 归属人 | `苟浩然` |

> **过滤规则**：`categoryText == "内部系统"` 的应用不是推广站（如 aicms），发文程序应排除。

### 2.3 一键登录：换取站点 access token ★核心

```http
POST /site/app-create-access-token
Authorization: Bearer {token}
Content-Type: application/json

{ "app": "cengguai" }
```

成功响应：

```json
{
  "code": 0,
  "data": {
    "id": 9,
    "name": "层乖整形",
    "signature": "cengguai",
    "url": "https://admin.cengguai.com/login",
    "token": {
      "name": "32 位十六进制字符串",
      "expire_at": "2026-10-15 17:17:53"
    }
  }
}
```

失败响应（站点侧故障或未授权）：

```json
{ "code": 3, "message": "您没有权限使用该应用！" }     // 账号对该站无权限
{ "code": 1, "message": "非常抱歉，系统出现错误！" }   // 站点域名失效 / 证书异常
```

> **token 三大特性（实测）**：
> 1. **短命**——`expire_at` 一般在签发后 **60 秒**内，必须立即使用；
> 2. **一次性**——第二次使用同一 token 立即失效，返回纯文本 `无效的访问令牌`；
> 3. **不可替代**——站点不接受账号密码，只认这个 token。

### 2.4 其他控制中心接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `/site/user-info` | GET | 当前登录用户信息（ID、手机号、昵称、权限菜单、角色） |
| `/system/app/category-tree` | GET | 应用分类树 |

---

## 3. 一键登录完整链路（独立站 / 合作站）

```
① POST center-admin-api/login/password-login          → 拿控制中心 Bearer token
② POST center-admin-api/site/app-create-access-token  → 拿站点一次性 token（约 60s 有效）
③ GET  {cms_url}?token={token}                        → 站点校验 token，下发 SESSID Cookie
④ GET  {站点}/article/category-tree                    → 已登录，返回栏目 JSON
⑤ POST {站点}/article/form                             → 发文成功
```

用 curl 复现第 ③ 步：

```bash
curl -i -c cookies.txt "https://admin.cengguai.com/login?token=<一次性token>"
# 响应头中 Set-Cookie: SESSID=xxxx  ← 之后所有业务请求都靠这个 Cookie
```

- **独立站/合作站**：`SESSID` Cookie 认证（Cookie 即会话，无 CSRF Token，无额外 Header）。
- **Cookie 有效期**：随站点服务端配置，通常数小时；过期后业务接口返回 `{"code":401}`，页面弹「登录状态已过期」并跳 `/login`。

---

## 4. 独立站 / 合作站 业务接口

以下接口在独立站与合作站上**行为一致**，基址为站点根域名（如 `https://admin.cengguai.com`）。

### 4.1 获取栏目列表

```http
GET /article/category-tree
```

响应：

```json
{
  "code": 0,
  "message": "",
  "data": [
    { "id": 1, "parent_id": 0, "name": "科普知识", "status": 1 },
    { "id": 2, "parent_id": 0, "name": "机构咨询", "status": 1 },
    { "id": 3, "parent_id": 0, "name": "医生讯息", "status": 1 },
    { "id": 4, "parent_id": 0, "name": "价格活动", "status": 1 }
  ]
}
```

备用端点（返回结构相同，字段含义一致）：

```http
GET /common/article-categorys
```

> 实测两接口栏目名略有差异（如 `科普知识` vs `医美整形-科普知识`），**共用同一套 id**。程序可在两个端点间做 fallback。
> 部分站点栏目为**两层结构**，`children` 字段承载子栏目。

### 4.2 发布文章 ★核心

```http
POST /article/form
Content-Type: application/json
Cookie: SESSID=xxxx
```

请求体（字段由站点表单页 `submit(article-form-submit)` 处理器一手确认）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✗ | 文章 ID。新增留空，编辑时填 |
| `title` | string | ✅ | 文章标题 |
| `category_id` | int | ✅ | 栏目 ID（来自 4.1） |
| `image` | string | ✗ | 封面图 URL（由 4.3 上传得到） |
| `file` | string | ✗ | 封面上传文件（提交表单时为空，仅上传组件使用） |
| `keywords` | string | ✗ | SEO 关键词 |
| `description` | string | ✗ | SEO 描述 |
| `view_count` | string/number | ✗ | 浏览量，默认 `0` |
| `published_at` | string | ✗ | 发布日期，格式 `YYYY-MM-DD HH:MM:SS`，缺省为当前时间 |
| `content` | string | ✅ | 正文 HTML（富文本，提交前做 `trim`） |
| `status` | int | ✗ | `1`=已发布（默认），`0`=待发布 |
| `_is_formatting` | string | ✗ | 内容格式化开关：`1`=强制清理 HTML 中的 style 属性与空白 p 标签，`0`=否 |

请求示例：

```json
{
  "id": "",
  "title": "面部填充术后的护理要点",
  "category_id": 1,
  "image": "https://static.xxx.com/uploads/2026/10/15/abc.jpg",
  "file": "",
  "keywords": "面部填充,术后护理,医美",
  "description": "面部填充术后如何护理？本文整理 5 个关键要点。",
  "view_count": "0",
  "published_at": "2026-10-15 18:00:00",
  "content": "<p>正文段落……</p>",
  "status": 1
}
```

响应：

```json
{ "code": 0, "message": "操作成功", "data": null }
```

错误码约定（站点前端 `app.$http` 封装）：

| code | 含义 | 处理 |
|---|---|---|
| `0` | 成功 | 正常 |
| `401` | 登录状态已过期 | 需重新一键登录 |
| 其他 | 业务错误 | 取 `message` 展示 |

### 4.3 上传图片（封面 / 正文图）

```http
POST /site/upload
Content-Type: multipart/form-data
Cookie: SESSID=xxxx

字段：
  type             = image | video | audio | document | archive
  file             = <二进制文件>
  save_attachment  = true | false    （是否存入附件库）
```

响应：

```json
{
  "code": 0,
  "message": "",
  "data": {
    "url": "https://static.xxx.com/uploads/2026/10/15/abc.jpg",
    "value": "uploads/2026/10/15/abc.jpg"
  }
}
```

- 封面场景：把 `data.value` 写入隐藏域 `#image`（即 4.2 的 `image` 字段）。
- **注意**：站点 Session 默认 `Content-Type: application/json`，上传时必须剔除该 Header 交给 requests 自动生成 multipart 边界，否则上传必失败。

### 4.4 文章列表页

```http
GET /article/index        → 返回「文章列表」HTML 管理页（非 JSON）
```

列表数据由页面内 layui table 异步拉取，字段结构（含 `id, uuid, category_id, title, image, description, view_count, published_at, status, created_at, updated_at, module_name, imageUrl, pageUrl, category`）已实测确认，可用于发布后核对。

### 4.5 端点存活实测（cengguai 站点）

| 端点 | GET | OPTIONS | 说明 |
|---|---|---|---|
| `/article/form` | 200 `text/html`（"添加文章"页） | 200 | ✅ 发文入口 |
| `/article/index` | 200 `text/html`（"文章列表"页） | 200 | ✅ 列表页 |
| `/article/category-tree` | 200 `application/json` | 204 `GET,POST,PUT,DELETE` | ✅ 栏目 JSON |
| `/common/article-categorys` | 200 `application/json` | 204 | ✅ 栏目 JSON（备用） |
| `/site/upload` | 404（GET 不支持，仅 POST） | 204 | ✅ 上传（仅 POST） |
| `/site/user-info` | 404 | 204 | ✗ 独立站无此接口 |
| `/article/delete`、`/article/del` | 404 | 204 | ✗ 未暴露 |

---

## 5. aicms（智能内容管理系统）接口

- 管理页：`https://aicms-admin.ruli.com`（Vue SPA）
- API 根：`https://aicms-admin-api.ruli.com`
- 认证：`Authorization: Bearer {token}`；前端 localStorage key 为 `aicms:token`

### 5.1 登录能力（实测：入口已关闭）

登录页字段：`admin_username`（手机号）、`admin_pwd`（密码）、`verify`（验证码，图片来自 `https://www.ruli.com/image-captcha`）。

```http
POST https://aicms-admin-api.ruli.com/login/password-login
Content-Type: application/json

{ "username": "...", "password": "...", "verify": "...", "remember": true }
```

用无效凭据实测返回：

```json
{ "code": 3, "message": "登录入口错误", "data": null }
```

> **对照组**：控制中心同类接口 `center-admin-api/login/password-login` 在凭据错误时返回的是「用户名或密码错误」——说明控制中心入口开放、而 aicms 入口被硬关闭（否则应返回"密码错误"而非"入口错误"）。

### 5.2 可用接口（Bearer 认证）

| 接口 | 方法 | 实测返回 |
|---|---|---|
| `/site/user-info` | GET | `{"code":0,...,"data":{"id":3,"phone":"...","nickname":"...","avatar":"..."}}` |
| `/site/dashboard` | GET | `{"code":0,...,"data":{"statistics":{"site_count":113}}}` |
| `/site/upload` | POST | 文件上传（同 4.3 的 multipart 约定） |
| `/site/logout` | POST | 退出 |
| `/site/user/profile` | GET/POST | 个人资料 |
| `/site/user-password` | POST | 修改密码 |
| `/site/user/binding` | POST | 账号绑定 |

### 5.3 内容工具接口（aicms 的真正用途）

aicms **不提供类似 `/article/form` 的单篇发文表单**（`/article/*` 在该 API 上返回 `{"code":404,"message":"接口不存在"}`）。它的定位是「批量内容工具」，前端 JS 中确认的路径有：

| 路径 | 用途 |
|---|---|
| `/content/tool/distribute` | 内容分发 |
| `/content/tool/generate` | 内容生成 |
| `/content/tool/time-refresh` | 内容发布时间刷新 |
| `/content/tool/word-delete-article` | 按关键词删除文章 |
| `/statistic/model-content` | 内容数据统计 |
| `/statistic/search-engine-spider-log` | 蜘蛛日志统计 |

### 5.4 aicms 的一键登录差异

aicms 走的是 `/site/take-new-token`（`POST`，body `{"token": "<一次性token>"}`）换取 Bearer token，而**不是**用 `?token=` 换 Cookie。实测该接口在 `aicms-admin-api.ruli.com` 域上 GET 返回 `{"code":404,"message":"接口不存在"}`（仅接受 POST）。

---

## 6. 站点能否单独登录？（对用户问题的直接回答）

### 6.1 站点确实保留了独立登录页

| 站点类型 | 登录页 | 字段 | 验证码 |
|---|---|---|---|
| 独立站 | `https://admin.<域名>/login`，标题「登录 - XXX管理后台」 | `username`(手机号) / `password` / `captcha` / `remember` | `/login/captcha`（下发 SESSID） |
| 合作站 | 同上（同构） | 同上 | 同上 |
| aicms | `https://aicms-admin.ruli.com/login` | `admin_username` / `admin_pwd` / `verify` | `www.ruli.com/image-captcha` |

页面形态、模板（Pear Admin + layui）、字段名、验证码接口全部**正常**——看起来是可以直接登录的。

### 6.2 但密码登录入口已被服务端统一关闭

**证据一 · 真实浏览器完整填写并提交**
用 Playwright 真实打开登录页，填写账号密码与验证码后提交，服务端统一返回：

```json
{ "code": 3, "message": "登录入口错误", "data": null }
```

**证据二 · 抽样 25 个独立站**
```
统计：登录入口错误 23 站 | 连接失败 1 站（cp-gas 域名解析失败）| 例外 0 站
```
**23/23 命中同一错误，0 例外。**

**证据三 · 协议层穷举 7 种组合**
| 组合 | 结果 |
|---|---|
| JSON + XHR 头 + Referer | 登录入口错误 |
| JSON 裸请求 | 登录入口错误 |
| form 表单编码 + XHR 头 + Referer | 登录入口错误 |
| form 表单编码 裸请求 | 登录入口错误 |
| JSON + 伪装控制中心 Referer | 登录入口错误 |
| JSON + 空 X-CSRF-Token | 登录入口错误 |
| JSON body + form Content-Type | 登录入口错误 |

→ 不是参数问题、不是 Header 问题、不是验证码问题，是**服务端主动拒绝密码登录这条通道**。

**证据四 · 后端不存在密码登录端点**
穷举 `/login/password-login`、`/login/verify`、`/login/check`、`/login/do`、`/login/submit`、`/site/login`、`/api/login`、`/user/login` 共 9 个候选端点，**全部 404**。唯一存活的 `/login` 端点（POST 提交表单的目标）固定返回「登录入口错误」。

**证据五 · 唯一被接受的通道是 token**
```
GET https://admin.cengguai.com/login?token=INVALID
→ 200，纯文本响应体："无效的访问令牌"（7 字节）
```
说明站点确实实现了「用 token 登录」这段逻辑，只是**只认控制中心签发的 token**。

### 6.3 结论

> **这些站点无法单独登录，必须依赖控制中心。**
>
> 站点侧虽保留登录页 UI，但账号密码登录入口已在服务端统一关闭（`登录入口错误`），后端也不存在对应的密码登录端点。站点唯一受支持的自助认证通道是 `GET {站点}/login?token=xxx`，而这个 token **只能由控制中心**通过 `POST /site/app-create-access-token` 签发，且有效期约 60 秒、一次性。
>
> 因此任何自动发文程序的**必经起点都是登录控制中心**：拿到控制中心 Bearer token → 换站点一次性 token → 换站点会话，三步缺一不可，没有旁路。

### 6.4 实践影响

- ✅ 自动化程序可以放心依赖控制中心账号：这是唯一入口，也是唯一需要维护的凭据。
- ✅ 站点账号密码**无需也不应保存**在配置里（存了也用不上）。
- ⚠️ 控制中心 token 有效期约 7 天，程序应处理过期重登。
- ⚠️ 站点 token 一次性，**并发/重试时切勿复用**，每个请求都要重新换。
- ⚠️ 换 token 失败（`您没有权限使用该应用！` / `非常抱歉，系统出现错误！`）属**站点或权限问题**，应把该站跳过并输出日志，而非反复重试。

---

## 7. 附录

### 7.1 一键登录最小可运行示例（Python）

```python
import requests

API = "https://center-admin-api.ruli.com"
s = requests.Session()

# ① 登录控制中心
token = s.post(f"{API}/login/password-login", json={
    "username": "手机号", "password": "密码", "remember": True
}).json()["data"]["token"]
H = {"Authorization": f"Bearer {token}"}

# ② 换站点一次性 token
d = s.post(f"{API}/site/app-create-access-token",
           json={"app": "cengguai"}, headers=H).json()["data"]
site_token, cms_url = d["token"]["name"], d["url"]

# ③ 用 token 换站点会话
base = cms_url.replace("/login", "").rstrip("/")
site = requests.Session()
site.get(f"{base}/login?token={site_token}")      # 拿到 SESSID Cookie

# ④ 取栏目
cats = site.get(f"{base}/article/category-tree").json()["data"]

# ⑤ 发文
r = site.post(f"{base}/article/form", json={
    "id": "", "title": "标题", "category_id": cats[0]["id"],
    "image": "", "file": "", "keywords": "关键词", "description": "描述",
    "view_count": "0", "published_at": "2026-10-15 18:00:00",
    "content": "<p>正文</p>", "status": 1,
}).json()
print(r)
```

### 7.2 实测数据索引（可复查）

| 文件 | 内容 |
|---|---|
| `scripts/real_chain_result.json` | 控制中心登录 → 换 token → 站点会话 → 栏目 → 表单页 全链路 |
| `scripts/independent_chain_result.json` | 独立站/合作站并发链路（含栏目样例、文章总数） |
| `scripts/login_sampling.json` | 25 站登录入口抽样统计 |
| `scripts/login_matrix_final.json` | 7 种协议组合穷举结果 |
| `scripts/login_endpoints.json` | 9 个候选登录端点探测（全 404） |
| `scripts/login_pages.json` | 三类站点登录页 DOM / 内联 JS / 请求记录 |
| `scripts/endpoint_probe.json` | 全端点零写入存活探测（GET/OPTIONS） |
| `scripts/article_form_inline.js` | 发文表单前端逻辑原文（字段与提交契约的一手证据） |
| `scripts/form_dom_result.json` | 发文表单字段 DOM 清单（含 label 与 placeholder） |
| `scripts/aicms_login_flow.json` | aicms 登录页字段与请求抓包 |
| `category_cache.json` | 111 个站点的栏目缓存 |
| `site_categories.json` | 90 个站点栏目映射 |

### 7.3 全链路接口清单速查

```
【控制中心】https://center-admin-api.ruli.com
  POST /login/password-login             登录（明文密码）
  GET  /site/user-info                   用户信息
  GET  /site/apps                        站点列表
  GET  /system/app/category-tree         应用分类树
  POST /site/app-create-access-token     换站点一次性 token ★

【独立站 / 合作站】https://admin.<域名>   （SESSID Cookie 认证）
  GET  /login?token=xxx                  用 token 换会话
  GET  /article/category-tree            栏目树
  GET  /common/article-categorys         栏目（备用）
  GET  /article/index                    文章列表页
  GET  /article/form                     添加文章页
  POST /article/form                     发布文章 ★
  POST /site/upload                      文件上传

【aicms】https://aicms-admin-api.ruli.com （Bearer 认证）
  POST /login/password-login             登录（入口已关闭）
  POST /site/take-new-token              换 token
  GET  /site/user-info                   用户信息
  GET  /site/dashboard                   仪表盘
  POST /site/upload                      文件上传
  POST /content/tool/distribute          内容分发
  POST /content/tool/generate            内容生成
  POST /content/tool/time-refresh        发布时间刷新
  POST /content/tool/word-delete-article 按关键词删文
```
