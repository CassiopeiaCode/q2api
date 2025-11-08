# Amazon Q to OpenAI API Bridge

将 Amazon Q Developer 转换为 OpenAI 兼容的 API 服务，支持流式和非流式响应。

## ✨ 核心特性

- **OpenAI 兼容接口** - 完全兼容 OpenAI Chat Completions API（`/v1/chat/completions`）
- **账号管理系统** - 支持多账号管理，启用/禁用控制，自动令牌刷新
- **设备授权登录** - 通过 URL 快速登录并自动创建账号（5分钟超时）
- **智能负载均衡** - 从启用的账号中随机选择，实现简单的负载分配
- **API Key 白名单** - 可选的访问控制，支持开发模式
- **现代化前端** - 美观的 Web 控制台，支持账号管理和 Chat 测试
- **自动重试机制** - Token 过期时自动刷新并重试请求

## 🚀 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
python -m venv .venv

# Windows
.venv\Scripts\activate
pip install -r requirements.txt

# Linux/macOS
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件
# OPENAI_KEYS="key1,key2,key3"  # 可选，留空则为开发模式
```

**配置说明：**
- `OPENAI_KEYS` 为空或未设置：开发模式，不校验 Authorization
- `OPENAI_KEYS` 设置后：仅白名单中的 key 可访问 API
- API Key 仅用于访问控制，不映射到特定账号

### 3. 启动服务

```bash
python -m uvicorn app:app --reload --port 8000
```

访问：
- 🏠 Web 控制台：http://localhost:8000/
- 💚 健康检查：http://localhost:8000/healthz

## 📖 使用指南

### 账号管理

#### 方式一：Web 控制台（推荐）

访问 http://localhost:8000/ 使用可视化界面管理账号：
- 查看所有账号及状态
- 创建/删除/编辑账号
- 启用/禁用账号
- 刷新 Token
- URL 登录（设备授权）

#### 方式二：REST API

**创建账号**
```bash
curl -X POST http://localhost:8000/v2/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "label": "我的账号",
    "clientId": "your-client-id",
    "clientSecret": "your-client-secret",
    "refreshToken": "your-refresh-token",
    "enabled": true
  }'
```

**列出所有账号**
```bash
curl http://localhost:8000/v2/accounts
```

**更新账号（切换启用状态）**
```bash
curl -X PATCH http://localhost:8000/v2/accounts/{account_id} \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

**刷新 Token**
```bash
curl -X POST http://localhost:8000/v2/accounts/{account_id}/refresh
```

**删除账号**
```bash
curl -X DELETE http://localhost:8000/v2/accounts/{account_id}
```

### URL 登录（设备授权）

快速添加账号的最简单方式：

1. **启动登录流程**
```bash
curl -X POST http://localhost:8000/v2/auth/start \
  -H "Content-Type: application/json" \
  -d '{"label": "新账号", "enabled": true}'
```

返回：
```json
{
  "authId": "xxx",
  "verificationUriComplete": "https://...",
  "userCode": "ABCD-1234",
  "expiresIn": 600,
  "interval": 1
}
```

2. **在浏览器中打开 `verificationUriComplete` 完成登录**

3. **等待并创建账号**（最多5分钟）
```bash
curl -X POST http://localhost:8000/v2/auth/claim/{authId}
```

成功后自动创建并启用账号。

### OpenAI 兼容 API

#### 非流式请求

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{
    "model": "claude-sonnet-4",
    "stream": false,
    "messages": [
      {"role": "system", "content": "你是一个乐于助人的助手"},
      {"role": "user", "content": "你好，请讲一个简短的故事"}
    ]
  }'
```

#### 流式请求（SSE）

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -d '{
    "model": "claude-sonnet-4",
    "stream": true,
    "messages": [
      {"role": "user", "content": "讲一个笑话"}
    ]
  }'
```

#### Python 示例

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-api-key"  # 如果配置了 OPENAI_KEYS
)

response = client.chat.completions.create(
    model="claude-sonnet-4",
    messages=[
        {"role": "user", "content": "你好"}
    ]
)

print(response.choices[0].message.content)
```

## 🔐 授权与账号选择

### 授权机制
- **开发模式**（`OPENAI_KEYS` 未设置）：不校验 Authorization
- **生产模式**（`OPENAI_KEYS` 已设置）：必须提供白名单中的 key

### 账号选择策略
- 从所有 `enabled=1` 的账号中**随机选择**
- API Key 不映射到特定账号
- 无可用账号时返回 401

### Token 刷新
- 请求时若账号缺少 accessToken，自动刷新
- 上游返回 401/403 时，自动刷新并重试一次
- 可手动调用刷新接口

## 📁 项目结构

```
.
├── app.py                          # FastAPI 主应用
├── auth_flow.py                    # 设备授权登录
├── replicate.py                    # Amazon Q 请求复刻
├── requirements.txt                # Python 依赖
├── .env.example                    # 环境变量示例
├── .gitignore                      # Git 忽略规则
├── data.sqlite3                    # SQLite 数据库（自动创建）
├── frontend/
│   └── index.html                  # Web 控制台
└── templates/
    └── streaming_request.json      # 请求模板
```

## 🛠️ 技术栈

- **后端**: FastAPI + Python 3.8+
- **数据库**: SQLite3
- **前端**: 纯 HTML/CSS/JavaScript
- **认证**: AWS OIDC 设备授权流程

## 🔧 高级配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_KEYS` | API Key 白名单（逗号分隔） | 空（开发模式） |

### 数据库结构

```sql
CREATE TABLE accounts (
    id TEXT PRIMARY KEY,
    label TEXT,
    clientId TEXT,
    clientSecret TEXT,
    refreshToken TEXT,
    accessToken TEXT,
    other TEXT,                    -- JSON 格式的额外信息
    last_refresh_time TEXT,
    last_refresh_status TEXT,
    created_at TEXT,
    updated_at TEXT,
    enabled INTEGER DEFAULT 1      -- 1=启用, 0=禁用
);
```

## 🐛 故障排查

### 401 Unauthorized
- 检查 `OPENAI_KEYS` 配置
- 确认至少有一个 `enabled=1` 的账号
- 验证账号的 clientId/clientSecret/refreshToken 正确

### Token 刷新失败
- 检查网络连接
- 验证 refreshToken 是否过期
- 查看账号的 `last_refresh_status` 字段

### 无响应/超时
- 检查 Amazon Q 服务可达性
- 查看服务日志排查错误

## 📝 API 端点

### 账号管理
- `POST /v2/accounts` - 创建账号
- `GET /v2/accounts` - 列出所有账号
- `GET /v2/accounts/{id}` - 获取账号详情
- `PATCH /v2/accounts/{id}` - 更新账号
- `DELETE /v2/accounts/{id}` - 删除账号
- `POST /v2/accounts/{id}/refresh` - 刷新 Token

### 设备授权
- `POST /v2/auth/start` - 启动登录流程
- `GET /v2/auth/status/{authId}` - 查询登录状态
- `POST /v2/auth/claim/{authId}` - 等待并创建账号

### OpenAI 兼容
- `POST /v1/chat/completions` - Chat Completions API

### 其他
- `GET /` - Web 控制台
- `GET /healthz` - 健康检查

## 📄 许可证

本项目仅供学习和测试使用。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！