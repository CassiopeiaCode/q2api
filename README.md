# Amazon Q to API Bridge

将 Amazon Q Developer 转换为兼容 OpenAI 和 Claude API 的服务，支持多账号管理、流式响应和智能负载均衡。

**项目地址：**
- GitHub: https://github.com/CassiopeiaCode/q2api
- Codeberg: https://codeberg.org/Korieu/amazonq2api

**致谢：**
- 感谢 [amq2api](https://github.com/mucsbr/amq2api) 项目提供的 Claude 消息格式转换参考

## ✨ 核心特性

### API 兼容性
- **OpenAI Chat Completions API** - 完全兼容 `/v1/chat/completions` 端点
- **Claude Messages API** - 完全兼容 `/v1/messages` 端点，支持流式和非流式
- **Tool Use 支持** - 完整支持 Claude 格式的工具调用和结果返回
- **System Prompt** - 支持系统提示词和多模态内容（文本、图片）

### 账号管理
- **多账号支持** - 管理多个 Amazon Q 账号，灵活启用/禁用
- **自动令牌刷新** - 后台定时刷新过期令牌，请求时自动重试
- **智能统计** - 自动统计成功/失败次数，错误超阈值自动禁用
- **设备授权登录** - 通过 URL 快速登录并自动创建账号（5分钟超时）

### 负载与监控
- **随机负载均衡** - 从启用的账号中随机选择，均衡分配负载
- **健康检查** - 实时监控服务状态
- **Web 控制台** - 美观的前端界面，支持账号管理和 Chat 测试

### 网络与安全
- **HTTP 代理支持** - 可配置代理服务器，支持所有 HTTP 请求
- **API Key 白名单** - 可选的访问控制，支持开发模式
- **持久化存储** - SQLite 数据库存储账号信息

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

最简单的部署方式，一键启动主服务和账号投喂服务：

```bash
# 1. 复制环境变量配置
cp .env.example .env

# 2. 编辑 .env 文件（可选）
# 配置 OPENAI_KEYS、MAX_ERROR_COUNT 等

# 3. 启动所有服务
docker-compose up -d

# 4. 查看日志
docker-compose logs -f

# 5. 停止服务
docker-compose down
```

服务访问地址：
- 🏠 主服务 Web 控制台：http://localhost:8000/
- 🎁 账号投喂服务：http://localhost:8001/
- 💚 健康检查：http://localhost:8000/healthz
- 📘 API 文档：http://localhost:8000/docs

### 方式二：本地开发

#### 1. 安装依赖

```bash
# 创建虚拟环境（推荐）
python -m venv .venv

# Windows
.venv\Scripts\activate
pip install -r requirements.txt

# Linux/macOS
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件配置以下选项：
```

**.env 配置说明：**

```bash
# ============ 主服务配置 ============

# OpenAI 风格 API Key 白名单（仅用于授权，与账号无关）
# 多个用逗号分隔，例如：OPENAI_KEYS="key1,key2,key3"
# 留空则为开发模式，不校验 Authorization
OPENAI_KEYS=""

# 出错次数阈值，超过此值自动禁用账号
MAX_ERROR_COUNT=100

# HTTP代理设置（留空不使用代理）
# 例如：HTTP_PROXY="http://127.0.0.1:7890"
HTTP_PROXY=""

# 管理控制台开关（默认启用）
# 设置为 "false" 或 "0" 可禁用管理控制台和相关API端点
ENABLE_CONSOLE="true"

# ============ 账号投喂服务配置 ============

# 投喂服务端口（默认 8001）
FEEDER_PORT=8001

# 主服务地址（投喂服务需要连接到主服务）
# Docker Compose 环境使用：http://q2api:8000
# 本地开发环境使用：http://localhost:8000
API_SERVER=http://localhost:8000
```

**配置要点：**
- `OPENAI_KEYS` 为空：开发模式，不校验 Authorization
- `OPENAI_KEYS` 设置后：仅白名单中的 key 可访问 API
- API Key 仅用于访问控制，不映射到特定账号
- 账号选择策略：从所有启用账号中随机选择
- `ENABLE_CONSOLE` 设为 `false` 或 `0`：禁用 Web 管理控制台和账号管理 API

#### 3. 启动服务

```bash
# 启动主服务（开发模式）
python -m uvicorn app:app --reload --port 8000

# 启动账号投喂服务（另一个终端）
cd account-feeder
python app.py
```

访问：
- 🏠 主服务 Web 控制台：http://localhost:8000/
- 🎁 账号投喂服务：http://localhost:8001/
- 💚 健康检查：http://localhost:8000/healthz
- 📘 API 文档：http://localhost:8000/docs

## 📖 使用指南

### 账号投喂服务 🎁

账号投喂服务是一个独立的 Web 应用，让其他人可以通过简单的 URL 登录方式投喂 Amazon Q 账号到主服务。

#### 特点
- ✅ 友好的 Web 界面，无需技术背景
- ✅ URL 登录（设备授权），5分钟内完成
- ✅ 支持手动输入凭据投喂
- ✅ 支持批量投喂账号
- ✅ 自动调用主服务创建账号

#### 使用方式

**方式一：URL 登录（推荐）**

1. 访问投喂服务：http://localhost:8001/
2. 填写账号标签（可选）
3. 点击"🚀 开始登录"按钮
4. 在自动打开的授权页面完成登录
5. 返回投喂页面，点击"⏳ 等待授权并创建账号"
6. 等待最多 5 分钟，账号自动创建并投喂到主服务

**方式二：手动投喂**

如果已有 `clientId`、`clientSecret`、`refreshToken`，可以直接在投喂页面的"手动投喂账号"区域填写并提交。

**方式三：批量投喂**

准备 JSON 数组格式的账号列表，在"批量投喂账号"区域粘贴并提交：

```json
[
  {
    "label": "账号1",
    "clientId": "xxx",
    "clientSecret": "xxx",
    "refreshToken": "xxx"
  },
  {
    "label": "账号2",
    "clientId": "yyy",
    "clientSecret": "yyy",
    "refreshToken": "yyy"
  }
]
```

#### 注意事项
- ⏱️ URL 登录有 5 分钟超时限制
- 🔗 确保主服务正常运行且可访问
- 🔒 建议在内网环境使用，避免暴露到公网

### 账号管理

#### 方式一：Web 控制台（推荐）

访问 http://localhost:8000/ 使用可视化界面：
- 查看所有账号及详细状态
- URL 登录（设备授权）快速添加账号
- 创建/删除/编辑账号
- 启用/禁用账号切换
- 手动刷新 Token
- Chat 功能测试

#### 方式二：URL 登录（最简单）

快速添加账号的推荐方式：

1. **启动登录流程**
```bash
curl -X POST http://localhost:8000/v2/auth/start \
  -H "Content-Type: application/json" \
  -d '{"label": "我的账号", "enabled": true}'
```

返回示例：
```json
{
  "authId": "xxx-xxx-xxx",
  "verificationUriComplete": "https://device.sso.us-east-1.amazonaws.com/?user_code=ABCD-1234",
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

成功后自动创建并启用账号，立即可用。

#### 方式三：REST API 手动管理

**创建账号**
```bash
curl -X POST http://localhost:8000/v2/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "label": "手动创建的账号",
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

**更新账号**
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

### Claude Messages API

本项目完整支持 Claude Messages API 格式，包括流式响应、工具调用、多模态内容等。

#### 基础文本对话

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{
    "model": "claude-sonnet-4.5",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'
```

#### 流式响应

```bash
curl -N -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{
    "model": "claude-sonnet-4.5",
    "max_tokens": 1024,
    "stream": true,
    "messages": [
      {"role": "user", "content": "写一首诗"}
    ]
  }'
```

#### 使用 System Prompt

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{
    "model": "claude-sonnet-4.5",
    "max_tokens": 1024,
    "system": "你是一个专业的Python程序员",
    "messages": [
      {"role": "user", "content": "如何实现快速排序？"}
    ]
  }'
```

#### Tool Use（工具调用）

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{
    "model": "claude-sonnet-4.5",
    "max_tokens": 1024,
    "tools": [
      {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "input_schema": {
          "type": "object",
          "properties": {
            "city": {"type": "string", "description": "城市名称"}
          },
          "required": ["city"]
        }
      }
    ],
    "messages": [
      {"role": "user", "content": "北京今天天气怎么样？"}
    ]
  }'
```

#### Tool Result（返回工具结果）

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{
    "model": "claude-sonnet-4.5",
    "max_tokens": 1024,
    "tools": [...],
    "messages": [
      {"role": "user", "content": "北京今天天气怎么样？"},
      {
        "role": "assistant",
        "content": [
          {"type": "text", "text": "我来查询北京的天气。"},
          {
            "type": "tool_use",
            "id": "toolu_xxx",
            "name": "get_weather",
            "input": {"city": "北京"}
          }
        ]
      },
      {
        "role": "user",
        "content": [
          {
            "type": "tool_result",
            "tool_use_id": "toolu_xxx",
            "content": "北京今天晴，温度15-25℃"
          }
        ]
      }
    ]
  }'
```

#### 多模态（图片）

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{
    "model": "claude-sonnet-4.5",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "这张图片里有什么？"},
          {
            "type": "image",
            "source": {
              "type": "base64",
              "media_type": "image/jpeg",
              "data": "/9j/4AAQSkZJRg..."
            }
          }
        ]
      }
    ]
  }'
```

#### Python SDK 示例

```python
from anthropic import Anthropic

client = Anthropic(
    base_url="http://localhost:8000/v1",
    api_key="your-api-key"
)

# 基础对话
message = client.messages.create(
    model="claude-sonnet-4.5",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "你好"}
    ]
)
print(message.content[0].text)

# 流式响应
with client.messages.stream(
    model="claude-sonnet-4.5",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "写一首诗"}
    ]
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
```

## 🔐 授权与账号选择

### 授权机制
- **开发模式**（`OPENAI_KEYS` 未设置）：不校验 Authorization
- **生产模式**（`OPENAI_KEYS` 已设置）：必须提供白名单中的 key

### 账号选择策略
- 从所有 `enabled=1` 的账号中**随机选择**
- API Key 不映射到特定账号（与 AWS 账号解耦）
- 无可用账号时返回 401

### Token 自动刷新
- **后台刷新**：每5分钟检查一次，超过25分钟未刷新的令牌自动刷新
- **请求时刷新**：若账号缺少 accessToken，自动刷新后重试
- **手动刷新**：支持通过 API 或 Web 控制台手动刷新

## 🏗️ 架构设计

### 核心模块

#### 1. app.py - FastAPI 主应用
- RESTful API 端点定义
- 账号管理（CRUD）
- 设备授权流程
- OpenAI 和 Claude API 端点
- SQLite 数据库操作
- 后台任务（令牌刷新）

#### 2. replicate.py - Amazon Q 请求复刻
- 加载请求模板
- 构建上游请求
- AWS Event Stream 解析
- 流式响应处理

#### 3. Claude 格式转换模块

**claude_types.py** - 类型定义
- `ClaudeRequest` - Claude API 请求格式
- `ClaudeMessage` - 消息格式
- `ClaudeTool` - 工具定义

**claude_converter.py** - 请求转换
- Claude 到 Amazon Q 格式转换
- Tool 定义转换
- 消息历史处理
- 多模态内容转换

**claude_parser.py** - 事件解析
- AWS Event Stream 二进制解析
- 事件头部解析
- JSON payload 提取

**claude_stream.py** - 流式响应处理
- Amazon Q 事件到 Claude SSE 格式转换
- Tool Use 状态管理
- 内容块流式输出

#### 4. auth_flow.py - 设备授权
- OIDC 客户端注册
- 设备授权流程
- 令牌轮询和获取

### 消息流程

```
用户请求
  │
  ├─→ OpenAI API (/v1/chat/completions)
  │     │
  │     └─→ 简单格式转换 → Amazon Q
  │
  └─→ Claude API (/v1/messages)
        │
        ├─→ claude_converter.py
        │     ├─ 转换 System Prompt
        │     ├─ 转换 Tools
        │     ├─ 转换 Messages
        │     └─ 转换多模态内容
        │
        ├─→ replicate.py
        │     ├─ 发送到 Amazon Q
        │     └─ 解析 Event Stream
        │
        └─→ claude_stream.py
              ├─ 事件转 Claude SSE
              ├─ 处理 Tool Use
              └─ 返回流式响应
```

## 📁 项目结构

```
.
├── app.py                          # FastAPI 主应用
├── replicate.py                    # Amazon Q 请求复刻
├── auth_flow.py                    # 设备授权登录
├── claude_types.py                 # Claude API 类型定义
├── claude_converter.py             # Claude 到 Amazon Q 转换
├── claude_parser.py                # Event Stream 解析
├── claude_stream.py                # Claude SSE 流式处理
├── requirements.txt                # Python 依赖
├── .env.example                    # 环境变量示例
├── .gitignore                      # Git 忽略规则
├── data.sqlite3                    # SQLite 数据库（自动创建）
├── templates/
│   └── streaming_request.json      # Amazon Q 请求模板
└── frontend/
    └── index.html                  # Web 控制台
```

## 🛠️ 技术栈

- **后端框架**: FastAPI + Python 3.8+
- **数据库**: SQLite3 + aiosqlite
- **HTTP 客户端**: httpx（支持异步和代理）
- **前端**: 纯 HTML/CSS/JavaScript（无依赖）
- **认证**: AWS OIDC 设备授权流程

## 🔧 高级配置

### 环境变量

| 变量 | 说明 | 默认值 | 示例 |
|------|------|--------|------|
| `OPENAI_KEYS` | API Key 白名单（逗号分隔） | 空（开发模式） | `"key1,key2"` |
| `MAX_ERROR_COUNT` | 错误次数阈值 | 100 | `50` |
| `HTTP_PROXY` | HTTP代理地址 | 空 | `"http://127.0.0.1:7890"` |
| `ENABLE_CONSOLE` | 管理控制台开关 | `"true"` | `"false"` |

### 数据库结构

```sql
CREATE TABLE accounts (
    id TEXT PRIMARY KEY,                -- UUID
    label TEXT,                         -- 账号标签
    clientId TEXT,                      -- OIDC 客户端 ID
    clientSecret TEXT,                  -- OIDC 客户端密钥
    refreshToken TEXT,                  -- 刷新令牌
    accessToken TEXT,                   -- 访问令牌
    other TEXT,                         -- JSON 格式的额外信息
    last_refresh_time TEXT,             -- 最后刷新时间
    last_refresh_status TEXT,           -- 最后刷新状态
    created_at TEXT,                    -- 创建时间
    updated_at TEXT,                    -- 更新时间
    enabled INTEGER DEFAULT 1,          -- 1=启用, 0=禁用
    error_count INTEGER DEFAULT 0,      -- 连续错误次数
    success_count INTEGER DEFAULT 0     -- 成功请求次数
);
```

### 账号统计与自动禁用

系统自动统计每个账号的请求结果：
- **成功**：返回至少1个有效字符，`success_count+1`，`error_count`重置为0
- **失败**：未返回有效字符或出错，`error_count+1`
- **自动禁用**：当 `error_count >= MAX_ERROR_COUNT` 时，账号自动设置为 `enabled=0`

这确保了有问题的账号不会持续影响服务质量。

### 后台任务

**Token 自动刷新**
- 每5分钟扫描一次所有启用的账号
- 超过25分钟未刷新的令牌自动刷新
- 刷新失败时记录状态和时间

## 📝 完整 API 端点列表

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
- `POST /v2/auth/claim/{authId}` - 等待并创建账号（最多5分钟）

### OpenAI 兼容
- `POST /v1/chat/completions` - Chat Completions API

### Claude 兼容
- `POST /v1/messages` - Messages API（支持流式、工具调用、多模态）

### 其他
- `GET /` - Web 控制台
- `GET /healthz` - 健康检查
- `GET /docs` - API 文档（Swagger UI）

## 🐛 故障排查

### 401 Unauthorized
**可能原因：**
- API Key 不在 `OPENAI_KEYS` 白名单中
- 没有启用的账号（`enabled=1`）
- 账号的 clientId/clientSecret/refreshToken 不正确

**解决方法：**
1. 检查 `.env` 中的 `OPENAI_KEYS` 配置
2. 访问 `/v2/accounts` 确认至少有一个启用的账号
3. 验证账号凭据是否正确

### Token 刷新失败
**可能原因：**
- refreshToken 已过期
- 网络连接问题
- OIDC 服务不可达

**解决方法：**
1. 查看账号的 `last_refresh_status` 字段
2. 检查网络连接和代理配置
3. 删除旧账号，通过 URL 登录重新添加

### 无响应/超时
**可能原因：**
- Amazon Q 服务不可达
- 网络问题
- 账号被限流

**解决方法：**
1. 检查 Amazon Q 服务状态
2. 查看服务日志排查错误
3. 尝试手动刷新令牌
4. 检查账号的 `error_count` 是否过高

### Claude API 工具调用问题
**可能原因：**
- 工具定义格式不正确
- Tool Result 格式不匹配
- 多轮对话历史处理错误

**解决方法：**
1. 参考文档中的示例格式
2. 确保 `tool_use_id` 正确对应
3. 检查消息历史中的 role 顺序

## 🚀 部署建议

### 生产环境

```bash
# 使用多个 worker 提高并发性能
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4

# 或使用 gunicorn
pip install gunicorn
gunicorn app:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Docker 部署

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t q2api .
docker run -p 8000:8000 -v $(pwd)/data.sqlite3:/app/data.sqlite3 q2api
```

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # SSE 支持
        proxy_buffering off;
        proxy_cache off;
    }
}
```

## 📊 性能优化

### 连接池配置
代码中已配置 httpx 连接池：
- `max_keepalive_connections`: 100
- `max_connections`: 200
- 超时设置：连接15秒，读取300秒

### 并发处理
- 使用异步 I/O（asyncio + FastAPI）
- 数据库使用 aiosqlite 异步操作
- 全局 HTTP 客户端复用

### 数据库优化
- WAL 模式提高并发读写性能
- 索引优化（主键索引）
- 定期清理过期数据

## 🔒 安全建议

1. **生产环境必须配置 `OPENAI_KEYS`**
2. **使用 HTTPS 反向代理（Nginx + Let's Encrypt）**
3. **定期备份 `data.sqlite3` 数据库**
4. **限制数据库文件权限**（仅应用可读写）
5. **监控错误日志，及时处理异常账号**
6. **配置防火墙规则，限制访问来源**

## 📄 许可证

本项目仅供学习和测试使用。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

**贡献指南：**
1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 🙏 致谢

- [amq2api](https://github.com/mucsbr/amq2api) - Claude 消息格式转换参考
- FastAPI - 现代 Python Web 框架
- Amazon Q Developer - 底层 AI 服务
