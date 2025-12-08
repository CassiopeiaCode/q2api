# 修复工具调用无限循环问题

## 问题描述

在使用多轮工具调用（Tool Use）对话时，AI 会重复调用相同的工具，进入无限循环。

### 用户报告的现象

```
用户: 帮我看一下 index.html 是否提交
AI: 好的我来帮你检查
*tool use: git diff
*tool use: git status  
*tool use: git log

AI: 用户说xxxx，好的我来帮你检查  ← 重复！
*tool use: git diff
*tool use: git status
*tool use: git log

AI: 用户说xxxx，我马上来检查  ← 又重复！
...无限循环...
```

### 抓包分析发现的问题

用户抓包发现：
1. 消息M（"你再查看一下index.html是否提交成功了"）一直在最后
2. **但是工具调用和结果却跑到了M的上面**
3. 多次tool_use和tool_result的顺序混乱
4. 整个对话历史被压缩成很少的消息块

## 根本原因

在 `claude_converter.py` 的 `process_history()` 函数中，存在一个"合并连续USER消息"的逻辑（第290-304行），这个逻辑**没有区分普通文本消息和包含tool_result的消息**，导致它们被错误地合并。

### 问题示例

**输入的Claude消息序列**：
```python
[
  {role: "user", content: "M: 检查文件"},           # 0
  {role: "assistant", content: [tool_use...]},      # 1  
  {role: "user", content: [tool_result...]},        # 2
  {role: "user", content: "用户的跟进问题"},         # 3 ← 连续的USER消息
  {role: "assistant", content: "..."},              # 4
]
```

**旧代码的输出**（错误）：
```python
history = [
  {userInputMessage: "M: 检查文件"},
  {assistantResponseMessage: [tool_use...]},
  {userInputMessage: "用户的跟进问题" + toolResults:[...]}  # ❌ 被合并了！
]
```

**问题**：
- messages[2]（tool_result）和 messages[3]（普通文本）被合并成一条
- tool_result 和普通文本混在一起
- AI 无法正确理解对话结构
- 导致 AI 重复执行工具调用

## 修复方案

修改 `process_history()` 函数，**不合并包含tool_result的USER消息**。

### 核心思路

1. 检测USER消息是否包含 `toolResults`
2. 如果包含，立即输出该消息（不加入pending队列）
3. 只合并纯文本的USER消息（不包含tool_result）

### 修复后的逻辑

```python
# Second pass: merge consecutive user messages (but NOT messages with tool results)
pending_user_msgs = []
for item in raw_history:
    if "userInputMessage" in item:
        user_msg = item["userInputMessage"]
        user_ctx = user_msg.get("userInputMessageContext", {})
        has_tool_results = "toolResults" in user_ctx and user_ctx["toolResults"]
        
        # 如果包含tool_result，不合并
        if has_tool_results:
            # 先输出pending的消息
            if pending_user_msgs:
                merged = merge_user_messages(pending_user_msgs)
                history.append({"userInputMessage": merged})
                pending_user_msgs = []
            # 然后直接添加这条tool_result消息（不合并）
            history.append(item)
        else:
            # 普通USER消息可以合并
            pending_user_msgs.append(user_msg)
    elif "assistantResponseMessage" in item:
        if pending_user_msgs:
            merged = merge_user_messages(pending_user_msgs)
            history.append({"userInputMessage": merged})
            pending_user_msgs = []
        history.append(item)
```

### 修复后的效果

**相同的输入，修复后的输出**（正确）：
```python
history = [
  {userInputMessage: "M: 检查文件"},
  {assistantResponseMessage: [tool_use...]},
  {userInputMessage: toolResults:[...]},           # ✅ 独立的tool_result
  {userInputMessage: "用户的跟进问题"},             # ✅ 独立的文本消息
]
```

**优势**：
- ✅ tool_result 消息保持独立
- ✅ 消息数量正确，不会丢失
- ✅ AI 可以看到完整的对话历史
- ✅ 消除了无限循环的根本原因

## 测试验证

### 测试1：标准工具调用流程

```python
输入: USER -> ASSISTANT(tool_use) -> USER(tool_result)
输出: 2条history + 1条current
结果: ✅ 通过
```

### 测试2：多轮工具调用

```python
输入: 
  USER -> ASSISTANT(tool_use) -> USER(tool_result) 
  -> ASSISTANT(tool_use) -> USER(tool_result)
输出: 4条history + 1条current
结果: ✅ 通过（每轮对话保持独立）
```

### 测试3：连续USER消息（包含tool_result）

```python
输入: 
  USER(M) -> ASSISTANT(tool_use) -> USER(tool_result) 
  -> USER(跟进问题) -> ASSISTANT
输出: 4条history + 1条current
  [0] USER: M
  [1] ASSISTANT: tool_use
  [2] USER: tool_result (独立)
  [3] USER: 跟进问题 (独立)
结果: ✅ 通过（tool_result和普通文本没有被合并）
```

## 相关改进

除了修复核心bug，还添加了以下改进：

### 1. 消息顺序验证

新增 `_validate_message_order()` 函数，验证：
- 首条消息必须是user
- 检测连续的相同角色消息（记录警告）
- 验证tool_result是否跟在tool_use之后

### 2. 增强的循环检测

改进 `_detect_tool_call_loop()` 函数：
- 检测完全相同的工具调用（名称+参数）
- 检测相同工具名的重复调用（即使参数不同）
- 记录警告日志

### 3. 调试模式

添加环境变量 `DEBUG_MESSAGE_CONVERSION`：
```bash
export DEBUG_MESSAGE_CONVERSION=true
```

启用后会输出详细的消息转换日志：
```
=== Message Conversion Debug ===
Input: 7 Claude messages
Output: 6 history messages + 1 current message
  History[0]: USER (toolResults: False)
  History[1]: ASSISTANT (toolUses: True)
  History[2]: USER (toolResults: True)
  ...
================================
```

## 使用建议

### 对于用户

1. **更新到最新版本**：此修复已合并到主分支
2. **启用调试模式**（可选）：设置 `DEBUG_MESSAGE_CONVERSION=true` 查看详细日志
3. **报告问题**：如果仍遇到循环，请提供完整的消息序列用于调试

### 对于开发者

1. **正确构建消息序列**：
   ```python
   # ✅ 正确
   messages = [
     {"role": "user", "content": "问题"},
     {"role": "assistant", "content": [tool_use...]},
     {"role": "user", "content": [tool_result...]},  # 独立的tool_result消息
   ]
   
   # ❌ 错误
   messages[0]["content"].append(tool_result)  # 不要把tool_result添加到其他消息中
   ```

2. **遵循Claude API规范**：
   - 消息必须 user-assistant 交替
   - tool_result 必须在独立的user消息中
   - tool_result 必须紧跟对应的tool_use

3. **实现轮次限制**：
   ```python
   MAX_ROUNDS = 5
   for round in range(MAX_ROUNDS):
       response = call_api(messages)
       if not has_tool_use(response):
           break
       # 执行工具并添加结果
   ```

## 相关资源

- [Claude API 工具使用文档](https://docs.anthropic.com/claude/docs/tool-use)
- [Issue讨论](https://github.com/CassiopeiaCode/q2api/issues)
- [完整排查指南](./TROUBLESHOOTING_INFINITE_LOOP.md)

## 总结

这个修复解决了工具调用无限循环的根本原因：**错误的消息合并**。通过确保tool_result消息保持独立，AI现在可以正确理解对话历史，从而避免重复调用工具。

修复影响：
- ✅ 解决无限循环问题
- ✅ 保持消息历史完整性
- ✅ 提高对话质量
- ✅ 减少不必要的API调用

---

**版本**: v1.0  
**日期**: 2025-12-08  
**修复PR**: [链接]
