# 思考功能 (Thinking Feature)

## 概述

q2api 现已支持 Claude API 的扩展思考功能。当启用思考模式时，模型会在响应中展示其推理过程。

## 功能特性

### 1. **原生 Claude API 兼容**
- 完全兼容 Claude API 的 `thinking` 参数
- 支持 `budget_tokens` 限制思考长度
- 返回标准的 `thinking` 类型 content block

### 2. **自动检测与转换**
- 自动识别 Amazon Q 响应中的思考内容
- 智能检测思考标记：`<thinking>`, `let me think`, `thinking:` 等
- 自动在思考块和文本块之间切换

### 3. **流式支持**
- 实时流式传输思考过程
- 独立的 `thinking_delta` 事件
- 完整的 token 统计（包含思考内容）

## 使用方法

### Python SDK 示例

```python
from anthropic import Anthropic

client = Anthropic(
    base_url="http://localhost:8000/v1",
    api_key="your-api-key"
)

# 启用思考模式
message = client.messages.create(
    model="claude-sonnet-4.5",
    max_tokens=2048,
    thinking={
        "type": "enabled",
        "budget_tokens": 1000  # 可选：限制思考使用的 token 数
    },
    messages=[
        {"role": "user", "content": "解释量子纠缠的原理"}
    ]
)

# 访问思考内容
for block in message.content:
    if block.type == "thinking":
        print(f"思考过程: {block.thinking}")
    elif block.type == "text":
        print(f"回答: {block.text}")
```

### 流式响应示例

```python
with client.messages.stream(
    model="claude-sonnet-4.5",
    max_tokens=2048,
    thinking={"type": "enabled"},
    messages=[
        {"role": "user", "content": "计算 123 * 456"}
    ]
) as stream:
    for event in stream:
        if event.type == "content_block_start":
            if event.content_block.type == "thinking":
                print("\n[开始思考]")
        elif event.type == "content_block_delta":
            if event.delta.type == "thinking_delta":
                print(event.delta.thinking, end="", flush=True)
            elif event.delta.type == "text_delta":
                print(event.delta.text, end="", flush=True)
```

### cURL 示例

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-api-key" \
  -d '{
    "model": "claude-sonnet-4.5",
    "max_tokens": 2048,
    "thinking": {
      "type": "enabled",
      "budget_tokens": 1000
    },
    "messages": [
      {"role": "user", "content": "What is 25 * 47?"}
    ],
    "stream": true
  }'
```

## 工作原理

### 1. 请求转换
当检测到 `thinking` 参数时，转换器会：
- 在发送给 Amazon Q 的提示词中注入思考指令
- 要求模型使用 `<thinking>` 标签包裹推理过程
- 可选地限制思考使用的 token 数量

### 2. 响应解析
流处理器会：
- 检测响应中的思考标记
- 自动创建 `thinking` 类型的 content block
- 将思考内容与最终答案分离

### 3. 事件流格式

**思考块开始：**
```json
{
  "type": "content_block_start",
  "index": 0,
  "content_block": {
    "type": "thinking",
    "thinking": ""
  }
}
```

**思考内容增量：**
```json
{
  "type": "content_block_delta",
  "index": 0,
  "delta": {
    "type": "thinking_delta",
    "thinking": "首先，我需要..."
  }
}
```

**思考块结束：**
```json
{
  "type": "content_block_stop",
  "index": 0
}
```

## 检测规则

### 思考开始标记
- `<thinking>`
- `let me think`
- `i need to think`
- `thinking:`
- `my reasoning`

### 思考结束标记
- `</thinking>`
- `now i'll`
- `now i will`
- `let me proceed`

## 注意事项

1. **启发式检测**：由于 Amazon Q 不原生支持思考模式，系统使用启发式规则检测思考内容
2. **Token 预算**：`budget_tokens` 参数会通过提示词传递给模型，但实际限制取决于模型的遵守程度
3. **兼容性**：完全兼容 Claude Code 和其他使用 Claude API 的客户端
4. **性能**：思考内容会增加响应时间和 token 消耗

## 测试

运行测试脚本：
```bash
python test_thinking.py
```

## 与 Claude Code 集成

Claude Code 会自动识别 `thinking` 类型的 content block，无需额外配置。只需在 API 请求中包含 `thinking` 参数即可。

## 故障排查

### 问题：没有返回思考内容
**解决方案：**
- 确保请求中包含 `thinking: {"type": "enabled"}`
- 检查模型是否理解思考指令
- 尝试在用户消息中明确要求展示推理过程

### 问题：思考内容混入文本块
**解决方案：**
- 检查思考标记是否正确（使用 `<thinking>` 标签）
- 调整 `_is_thinking_content()` 方法中的检测规则

### 问题：思考块过早结束
**解决方案：**
- 检查结束标记的检测逻辑
- 确保 `</thinking>` 标签正确闭合
