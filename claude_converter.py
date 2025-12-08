import json
import uuid
import time
import logging
from datetime import datetime
import os
from typing import List, Dict, Any, Optional, Union

try:
    from .claude_types import ClaudeRequest, ClaudeMessage, ClaudeTool
except ImportError:
    # Fallback for dynamic loading where relative import might fail
    # We assume claude_types is available in sys.modules or we can import it directly if in same dir
    import sys
    if "v2.claude_types" in sys.modules:
        from v2.claude_types import ClaudeRequest, ClaudeMessage, ClaudeTool
    else:
        # Try absolute import assuming v2 is in path or current dir
        try:
            from claude_types import ClaudeRequest, ClaudeMessage, ClaudeTool
        except ImportError:
             # Last resort: if loaded via importlib in app.py, we might need to rely on app.py injecting it
             # But app.py loads this module.
             pass

logger = logging.getLogger(__name__)

# Debug mode for detailed logging of message conversion
DEBUG_MESSAGE_CONVERSION = os.getenv("DEBUG_MESSAGE_CONVERSION", "false").lower() in ("true", "1", "yes")
THINKING_HINT = "<antml:thinking_mode>interleaved</antml:thinking_mode><antml:max_thinking_length>16000</antml:max_thinking_length>"
THINKING_START_TAG = "<thinking>"
THINKING_END_TAG = "</thinking>"

def _wrap_thinking_content(thinking_text: str) -> str:
    """Wrap thinking text with the XML tag expected by Amazon Q."""
    return f"{THINKING_START_TAG}{thinking_text}{THINKING_END_TAG}"

def is_thinking_mode_enabled(thinking_cfg: Optional[Any]) -> bool:
    """Detect whether the client enabled thinking mode."""
    if thinking_cfg is None:
        return False
    if isinstance(thinking_cfg, bool):
        return thinking_cfg
    if isinstance(thinking_cfg, str):
        return thinking_cfg.lower() == "enabled"
    if isinstance(thinking_cfg, dict):
        type_val = str(thinking_cfg.get("type", "")).lower()
        if type_val == "enabled":
            return True
        enabled_flag = thinking_cfg.get("enabled")
        if isinstance(enabled_flag, bool):
            return enabled_flag
        budget = thinking_cfg.get("budget_tokens")
        if isinstance(budget, (int, float)) and budget > 0:
            return True
    return False

def _append_thinking_hint(text: str, hint: str = THINKING_HINT) -> str:
    """Append the special hint once to the end of the text."""
    text = text or ""
    normalized = text.rstrip()
    if normalized.endswith(hint):
        return text
    if not text:
        return hint
    separator = "" if text.endswith(("\n", "\r")) else "\n"
    return f"{text}{separator}{hint}"

def get_current_timestamp() -> str:
    """Get current timestamp in Amazon Q format."""
    now = datetime.now().astimezone()
    weekday = now.strftime("%A")
    iso_time = now.isoformat(timespec='milliseconds')
    return f"{weekday}, {iso_time}"

def map_model_name(claude_model: str) -> str:
    """Map Claude model name to Amazon Q model ID."""
    model_lower = claude_model.lower()
    if model_lower.startswith("claude-sonnet-4.5") or model_lower.startswith("claude-sonnet-4-5"):
        return "claude-sonnet-4.5"
    return "claude-sonnet-4"

def extract_text_from_content(content: Union[str, List[Dict[str, Any]]]) -> str:
    """Extract text from Claude content."""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    parts.append(block.get("text", ""))
                elif block_type == "thinking":
                    parts.append(_wrap_thinking_content(block.get("thinking", "")))
        return "\n".join(parts)
    return ""

def extract_images_from_content(content: Union[str, List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """Extract images from Claude content and convert to Amazon Q format."""
    if not isinstance(content, list):
        return None
    
    images = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "image":
            source = block.get("source", {})
            if source.get("type") == "base64":
                media_type = source.get("media_type", "image/png")
                fmt = media_type.split("/")[-1] if "/" in media_type else "png"
                images.append({
                    "format": fmt,
                    "source": {
                        "bytes": source.get("data", "")
                    }
                })
    return images if images else None

def convert_tool(tool: ClaudeTool) -> Dict[str, Any]:
    """Convert Claude tool to Amazon Q tool."""
    desc = tool.description or ""
    if len(desc) > 10240:
        desc = desc[:10100] + "\n\n...(Full description provided in TOOL DOCUMENTATION section)"
    
    return {
        "toolSpecification": {
            "name": tool.name,
            "description": desc,
            "inputSchema": {"json": tool.input_schema}
        }
    }

def merge_user_messages(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge consecutive user messages, keeping only the last 2 messages' images."""
    if not messages:
        return {}
    
    all_contents = []
    base_context = None
    base_origin = None
    base_model = None
    all_images = []
    
    for msg in messages:
        content = msg.get("content", "")
        if base_context is None:
            base_context = msg.get("userInputMessageContext", {})
        if base_origin is None:
            base_origin = msg.get("origin", "CLI")
        if base_model is None:
            base_model = msg.get("modelId")
        
        if content:
            all_contents.append(content)
        
        # Collect images from each message
        msg_images = msg.get("images")
        if msg_images:
            all_images.append(msg_images)
    
    result = {
        "content": "\n\n".join(all_contents),
        "userInputMessageContext": base_context or {},
        "origin": base_origin or "CLI",
        "modelId": base_model
    }
    
    # Only keep images from the last 2 messages that have images
    if all_images:
        kept_images = []
        for img_list in all_images[-2:]:  # Take last 2 messages' images
            kept_images.extend(img_list)
        if kept_images:
            result["images"] = kept_images
    
    return result

def process_history(messages: List[ClaudeMessage], thinking_enabled: bool = False, hint: str = THINKING_HINT) -> List[Dict[str, Any]]:
    """Process history messages to match Amazon Q format (alternating user/assistant)."""
    history = []
    seen_tool_use_ids = set()
    
    raw_history = []
    
    # First pass: convert individual messages
    for msg in messages:
        if msg.role == "user":
            content = msg.content
            text_content = ""
            tool_results = None
            images = extract_images_from_content(content)
            should_append_hint = thinking_enabled
            
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        btype = block.get("type")
                        if btype == "text":
                            text_parts.append(block.get("text", ""))
                        elif btype == "thinking":
                            text_parts.append(_wrap_thinking_content(block.get("thinking", "")))
                        elif btype == "tool_result":
                            if tool_results is None:
                                tool_results = []
                            
                            tool_use_id = block.get("tool_use_id")
                            raw_c = block.get("content", [])
                            
                            aq_content = []
                            if isinstance(raw_c, str):
                                aq_content = [{"text": raw_c}]
                            elif isinstance(raw_c, list):
                                for item in raw_c:
                                    if isinstance(item, dict):
                                        if item.get("type") == "text":
                                            aq_content.append({"text": item.get("text", "")})
                                        elif "text" in item:
                                            aq_content.append({"text": item["text"]})
                                    elif isinstance(item, str):
                                        aq_content.append({"text": item})
                            
                            if not any(i.get("text", "").strip() for i in aq_content):
                                aq_content = [{"text": "Tool use was cancelled by the user"}]
                                
                            # Merge if exists
                            existing = next((r for r in tool_results if r["toolUseId"] == tool_use_id), None)
                            if existing:
                                existing["content"].extend(aq_content)
                            else:
                                tool_results.append({
                                    "toolUseId": tool_use_id,
                                    "content": aq_content,
                                    "status": block.get("status", "success")
                                })
                text_content = "\n".join(text_parts)
            else:
                text_content = extract_text_from_content(content)
            
            if should_append_hint:
                text_content = _append_thinking_hint(text_content, hint)
            
            user_ctx = {
                "envState": {
                    "operatingSystem": "macos",
                    "currentWorkingDirectory": "/"
                }
            }
            if tool_results:
                user_ctx["toolResults"] = tool_results
                
            u_msg = {
                "content": text_content,
                "userInputMessageContext": user_ctx,
                "origin": "CLI"
            }
            if images:
                u_msg["images"] = images
                
            raw_history.append({"userInputMessage": u_msg})
            
        elif msg.role == "assistant":
            content = msg.content
            text_content = extract_text_from_content(content)
            
            entry = {
                "assistantResponseMessage": {
                    "messageId": str(uuid.uuid4()),
                    "content": text_content
                }
            }
            
            if isinstance(content, list):
                tool_uses = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tid = block.get("id")
                        if tid and tid not in seen_tool_use_ids:
                            seen_tool_use_ids.add(tid)
                            tool_uses.append({
                                "toolUseId": tid,
                                "name": block.get("name"),
                                "input": block.get("input", {})
                            })
                if tool_uses:
                    entry["assistantResponseMessage"]["toolUses"] = tool_uses
            
            raw_history.append(entry)

    # Second pass: merge consecutive user messages (but NOT messages with tool results)
    # Tool result messages must remain separate to preserve the conversation flow that AI models 
    # expect when processing tool execution history. Merging tool results with other messages
    # causes the AI to lose track of completed tool calls, leading to infinite loops.
    pending_user_msgs = []
    for item in raw_history:
        if "userInputMessage" in item:
            user_msg = item["userInputMessage"]
            user_ctx = user_msg.get("userInputMessageContext", {})
            has_tool_results = "toolResults" in user_ctx and user_ctx["toolResults"]
            
            # If this user message has tool results, don't merge it
            if has_tool_results:
                # First, flush any pending user messages
                if pending_user_msgs:
                    merged = merge_user_messages(pending_user_msgs)
                    history.append({"userInputMessage": merged})
                    pending_user_msgs = []
                # Then add this tool result message directly (don't merge)
                history.append(item)
            else:
                # Regular user message without tool results - can be merged
                pending_user_msgs.append(user_msg)
        elif "assistantResponseMessage" in item:
            if pending_user_msgs:
                merged = merge_user_messages(pending_user_msgs)
                history.append({"userInputMessage": merged})
                pending_user_msgs = []
            history.append(item)
            
    if pending_user_msgs:
        merged = merge_user_messages(pending_user_msgs)
        history.append({"userInputMessage": merged})
        
    return history

def _validate_message_order(messages: List[ClaudeMessage]) -> Optional[str]:
    """Validate that messages follow the correct user-assistant alternating pattern.
    
    Claude API requires messages to alternate between user and assistant roles.
    Tool results must be in a user message that follows an assistant message with tool_use.
    
    Returns error message if validation fails, None otherwise.
    """
    if not messages:
        return None
    
    # Check first message is from user
    if messages[0].role != "user":
        return "First message must be from user role"
    
    # Track expected role and tool_use state
    prev_role = None
    has_pending_tool_use = False
    pending_tool_ids = set()
    
    for i, msg in enumerate(messages):
        # Check alternating pattern
        if prev_role is not None and msg.role == prev_role:
            logger.warning(f"Message {i}: Found consecutive {msg.role} messages. This may cause issues with conversation flow.")
        
        if msg.role == "assistant" and isinstance(msg.content, list):
            # Check for tool_use blocks
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    has_pending_tool_use = True
                    tool_id = block.get("id")
                    if tool_id:
                        pending_tool_ids.add(tool_id)
        
        elif msg.role == "user" and isinstance(msg.content, list):
            # Check for tool_result blocks
            found_tool_results = False
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    found_tool_results = True
                    tool_use_id = block.get("tool_use_id")
                    if tool_use_id and tool_use_id in pending_tool_ids:
                        pending_tool_ids.remove(tool_use_id)
            
            # If we have tool results, we should have had pending tool_use
            if found_tool_results and not has_pending_tool_use and i > 0:
                # Check if previous message was assistant with tool_use
                if i > 0 and messages[i-1].role == "assistant":
                    # This is OK, tool results following assistant message
                    pass
                else:
                    logger.warning(f"Message {i}: Found tool_result but no recent tool_use from assistant. Message order may be incorrect.")
            
            if found_tool_results:
                has_pending_tool_use = False  # Reset after processing results
        
        prev_role = msg.role
    
    # Warning if there are unclaimed tool_use calls
    if pending_tool_ids:
        logger.warning(f"Conversation ended with {len(pending_tool_ids)} tool_use calls without corresponding tool_result")
    
    return None

def _detect_tool_call_loop(messages: List[ClaudeMessage], threshold: int = 3) -> Optional[str]:
    """Detect if the same tool is being called repeatedly (potential infinite loop)."""
    recent_tool_calls = []
    for msg in messages[-10:]:  # Check last 10 messages
        if msg.role == "assistant" and isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_name = block.get("name")
                    tool_input = json.dumps(block.get("input", {}), sort_keys=True)
                    recent_tool_calls.append((tool_name, tool_input))

    if len(recent_tool_calls) >= threshold:
        # Check if the last N tool calls are identical
        last_calls = recent_tool_calls[-threshold:]
        if len(set(last_calls)) == 1:
            return f"Detected infinite loop: tool '{last_calls[0][0]}' called {threshold} times with same input"
        
        # Also check for similar tool names (same tool name, different or similar inputs)
        tool_names_only = [call[0] for call in last_calls]
        if len(set(tool_names_only)) == 1:
            # Same tool called multiple times with different inputs
            logger.warning(f"Tool '{tool_names_only[0]}' called {threshold} times recently with potentially different inputs. This might indicate a loop.")

    return None

def convert_claude_to_amazonq_request(req: ClaudeRequest, conversation_id: Optional[str] = None) -> Dict[str, Any]:
    """Convert ClaudeRequest to Amazon Q request body."""
    if conversation_id is None:
        conversation_id = str(uuid.uuid4())

    # Validate message order
    validation_error = _validate_message_order(req.messages)
    if validation_error:
        logger.error(f"Message validation failed: {validation_error}")
        # Continue processing despite validation errors to maintain backwards compatibility
        # and allow recovery from minor message order issues. Most validation failures are
        # warnings rather than fatal errors that would prevent processing.

    # Detect infinite tool call loops
    loop_error = _detect_tool_call_loop(req.messages, threshold=3)
    if loop_error:
        raise ValueError(loop_error)

    thinking_enabled = is_thinking_mode_enabled(getattr(req, "thinking", None))
        
    # 1. Tools
    aq_tools = []
    long_desc_tools = []
    if req.tools:
        for t in req.tools:
            if t.description and len(t.description) > 10240:
                long_desc_tools.append({"name": t.name, "full_description": t.description})
            aq_tools.append(convert_tool(t))
            
    # 2. Current Message (last user message)
    last_msg = req.messages[-1] if req.messages else None
    prompt_content = ""
    tool_results = None
    has_tool_result = False
    images = None
    
    if last_msg and last_msg.role == "user":
        content = last_msg.content
        images = extract_images_from_content(content)
        
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "thinking":
                        text_parts.append(_wrap_thinking_content(block.get("thinking", "")))
                    elif btype == "tool_result":
                        has_tool_result = True
                        if tool_results is None:
                            tool_results = []
                        
                        tid = block.get("tool_use_id")
                        raw_c = block.get("content", [])
                        
                        aq_content = []
                        if isinstance(raw_c, str):
                            aq_content = [{"text": raw_c}]
                        elif isinstance(raw_c, list):
                            for item in raw_c:
                                if isinstance(item, dict):
                                    if item.get("type") == "text":
                                        aq_content.append({"text": item.get("text", "")})
                                    elif "text" in item:
                                        aq_content.append({"text": item["text"]})
                                elif isinstance(item, str):
                                    aq_content.append({"text": item})
                                    
                        if not any(i.get("text", "").strip() for i in aq_content):
                            aq_content = [{"text": "Tool use was cancelled by the user"}]
                            
                        existing = next((r for r in tool_results if r["toolUseId"] == tid), None)
                        if existing:
                            existing["content"].extend(aq_content)
                        else:
                            tool_results.append({
                                "toolUseId": tid,
                                "content": aq_content,
                                "status": block.get("status", "success")
                            })
            prompt_content = "\n".join(text_parts)
        else:
            prompt_content = extract_text_from_content(content)

        if thinking_enabled:
            prompt_content = _append_thinking_hint(prompt_content)
            
    # 3. Context
    user_ctx = {
        "envState": {
            "operatingSystem": "macos",
            "currentWorkingDirectory": "/"
        }
    }
    if aq_tools:
        user_ctx["tools"] = aq_tools
    if tool_results:
        user_ctx["toolResults"] = tool_results
        
    # 4. Format Content
    formatted_content = ""
    if has_tool_result and not prompt_content:
        formatted_content = ""
    else:
        formatted_content = (
            "--- CONTEXT ENTRY BEGIN ---\n"
            f"Current time: {get_current_timestamp()}\n"
            "--- CONTEXT ENTRY END ---\n\n"
            "--- USER MESSAGE BEGIN ---\n"
            f"{prompt_content}\n"
            "--- USER MESSAGE END ---"
        )
        
    if long_desc_tools:
        docs = []
        for info in long_desc_tools:
            docs.append(f"Tool: {info['name']}\nFull Description:\n{info['full_description']}\n")
        formatted_content = (
            "--- TOOL DOCUMENTATION BEGIN ---\n"
            f"{''.join(docs)}"
            "--- TOOL DOCUMENTATION END ---\n\n"
            f"{formatted_content}"
        )
        
    if req.system and formatted_content:
        sys_text = ""
        if isinstance(req.system, str):
            sys_text = req.system
        elif isinstance(req.system, list):
            parts = []
            for b in req.system:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(b.get("text", ""))
            sys_text = "\n".join(parts)
            
        if sys_text:
            formatted_content = (
                "--- SYSTEM PROMPT BEGIN ---\n"
                f"{sys_text}\n"
                "--- SYSTEM PROMPT END ---\n\n"
                f"{formatted_content}"
            )
            
    # 5. Model
    model_id = map_model_name(req.model)
    
    # 6. User Input Message
    user_input_msg = {
        "content": formatted_content,
        "userInputMessageContext": user_ctx,
        "origin": "CLI",
        "modelId": model_id
    }
    if images:
        user_input_msg["images"] = images
        
    # 7. History
    history_msgs = req.messages[:-1] if len(req.messages) > 1 else []
    aq_history = process_history(history_msgs, thinking_enabled=thinking_enabled, hint=THINKING_HINT)
    
    # 8. Final Body
    result = {
        "conversationState": {
            "conversationId": conversation_id,
            "history": aq_history,
            "currentMessage": {
                "userInputMessage": user_input_msg
            },
            "chatTriggerType": "MANUAL"
        }
    }
    
    # Debug logging
    if DEBUG_MESSAGE_CONVERSION:
        logger.info(f"=== Message Conversion Debug ===")
        logger.info(f"Input: {len(req.messages)} Claude messages")
        logger.info(f"Output: {len(aq_history)} history messages + 1 current message")
        for i, msg in enumerate(aq_history):
            if "userInputMessage" in msg:
                has_tr = "toolResults" in msg["userInputMessage"].get("userInputMessageContext", {})
                logger.info(f"  History[{i}]: USER (toolResults: {has_tr})")
            elif "assistantResponseMessage" in msg:
                has_tu = "toolUses" in msg["assistantResponseMessage"]
                logger.info(f"  History[{i}]: ASSISTANT (toolUses: {has_tu})")
        has_tr_current = "toolResults" in user_input_msg.get("userInputMessageContext", {})
        logger.info(f"  Current: USER (toolResults: {has_tr_current})")
        logger.info(f"================================")
    
    return result
