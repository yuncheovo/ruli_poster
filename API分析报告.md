# Ruli CMS API 分析报告

## 控制中心 (center-admin.ruli.com)

### API基础地址
- **管理页面**: `https://center-admin.ruli.com`
- **API地址**: `https://center-admin-api.ruli.com`

### 1. 登录
```
POST https://center-admin-api.ruli.com/login/password-login
Content-Type: application/json

请求:
{
  "username": "19136245159",
  "password": "r22w8xqCtXvZgffSrJEV",
  "remember": true
}

响应:
{
  "code": 0,
  "message": "恭喜您，登录成功！",
  "data": {
    "token": "xxx",
    "expire_at": "2026-06-29 16:23:13"
  }
}
```

**注意**: 密码是**明文传输**，不需要AES加密。

### 2. 获取用户信息
```
GET https://center-admin-api.ruli.com/site/user-info
Authorization: Bearer {token}

响应包含：
- 用户ID、手机号、昵称
- 权限菜单列表 (authorities)
- 角色列表 (roles)
```

### 3. 获取站点列表
```
GET https://center-admin-api.ruli.com/site/apps?page=1&limit=100
Authorization: Bearer {token}

响应:
{
  "code": 0,
  "data": {
    "total": 37,
    "items": [
      {
        "id": 2,
        "name": "智能内容管理系统",
        "signature": "aicms",
        "url": "https://aicms-admin.ruli.com/login",
        "created_at": "2026-01-29 12:45:38",
        "categoryText": "内部系统",
        "ownerText": "超管员"
      }
    ]
  }
}
```

### 4. 获取分类树
```
GET https://center-admin-api.ruli.com/system/app/category-tree
Authorization: Bearer {token}
```

### 5. 一键登录 - 获取访问令牌
```
POST https://center-admin-api.ruli.com/site/app-create-access-token
Authorization: Bearer {token}
Content-Type: application/json

请求:
{
  "app": "nouhua"  // 站点的signature
}

响应:
{
  "code": 0,
  "data": {
    "id": 9,
    "name": "诺华整形",
    "signature": "nouhua",
    "url": "https://admin.nouhua.com/login",
    "token": {
      "name": "xxx",
      "expire_at": "2026-06-22 16:35:04"
    }
  }
}
```

## 一键登录流程

1. 调用 `/site/app-create-access-token` 获取token
2. 携带token访问目标CMS: `{cms_url}?token={token}`
3. 目标CMS通过 `POST {cms_api}/site/take-new-token` 交换session token
4. CMS API域名规律: `admin.xxx.com` → `admin-api.xxx.com`

## 目标CMS API (aicms示例)

### API地址规律
- 管理页面: `https://aicms-admin.ruli.com`
- API地址: `https://aicms-admin-api.ruli.com`

### 已知端点
- `POST /site/take-new-token` - token交换
- `GET /site/user-info` - 用户信息
- `GET /site/dashboard` - 仪表盘数据
- `POST /site/upload` - 文件上传

### 菜单结构
- 系统概况
- 数据统计
  - 蜘蛛日志统计
  - 内容数据统计
- 生成工具
  - 内容分发
  - 内容发布时间刷新
  - 根据关键字删除文章

## 鉴权方式

- 控制中心: `Authorization: Bearer {token}` (无前缀Bearer也行)
- localStorage key: `control:token`
- 目标CMS: `Authorization: Bearer {token}`
- localStorage key: `{signature}:token`
