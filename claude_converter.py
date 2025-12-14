import json
import uuid
import time
import logging
from datetime import datetime
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
    """Map Claude model name to Amazon Q model ID.

    Accepts both short names (e.g., claude-sonnet-4) and canonical names
    (e.g., claude-sonnet-4-20250514).
    """
    DEFAULT_MODEL = "claude-sonnet-4.5"

    # Available models in the service (Amazon Q only supports these)
    VALID_MODELS = {"auto", "claude-sonnet-4", "claude-sonnet-4.5", "claude-haiku-4.5"}

    # Mapping from canonical names to short names
    CANONICAL_TO_SHORT = {
        "claude-sonnet-4-20250514": "claude-sonnet-4",
        "claude-sonnet-4-5-20250929": "claude-sonnet-4.5",
        "claude-haiku-4-5-20251001": "claude-haiku-4.5",
        # Amazon Q doesn't support Opus - map to Sonnet 4.5 (best available model)
        "claude-opus-4-5-20251101": "claude-sonnet-4.5",
        # Legacy Claude 3.5 Sonnet models
        "claude-3-5-sonnet-20241022": "claude-sonnet-4.5",
        "claude-3-5-sonnet-20240620": "claude-sonnet-4.5",
    }

    model_lower = claude_model.lower()

    # Check if it's a valid short name (but not "auto" which Amazon Q doesn't accept)
    if model_lower in VALID_MODELS and model_lower != "auto":
        return model_lower

    # Check if it's a canonical name
    if model_lower in CANONICAL_TO_SHORT:
        return CANONICAL_TO_SHORT[model_lower]

    # Unknown model - log warning and return default
    logger.warning(f"Unknown model '{claude_model}', falling back to default model '{DEFAULT_MODEL}'")
    return DEFAULT_MODEL

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

def merge_user_messages(messages: List[Dict[str, Any]], hint: str = THINKING_HINT) -> Dict[str, Any]:
    """Merge consecutive user messages, keeping only the last 2 messages' images.
    
    IMPORTANT: This function properly merges toolResults from all messages to prevent
    losing tool execution history, which would cause infinite loops.
    
    When merging messages that contain thinking hints, removes duplicate hints and 
    ensures only one hint appears at the end of the merged content.
    
    Args:
        messages: List of user messages to merge
        hint: The thinking hint string to deduplicate
    """
    if not messages:
        return {}
    
    all_contents = []
    base_context = None
    base_origin = None
    base_model = None
    all_images = []
    all_tool_results = []  # Collect toolResults from all messages
    
    for msg in messages:
        content = msg.get("content", "")
        msg_ctx = msg.get("userInputMessageContext", {})
        
        # Initialize base context from first message
        if base_context is None:
            base_context = msg_ctx.copy() if msg_ctx else {}
            # Remove toolResults from base to merge them separately
            if "toolResults" in base_context:
                all_tool_results.extend(base_context.pop("toolResults"))
        else:
            # Collect toolResults from subsequent messages
            if "toolResults" in msg_ctx:
                all_tool_results.extend(msg_ctx["toolResults"])
        
        if base_origin is None:
            base_origin = msg.get("origin", "KIRO_CLI")
        if base_model is None:
            base_model = msg.get("modelId")
        
        # Remove thinking hint from individual message content to avoid duplication
        # The hint will be added once at the end of the merged content
        if content:
            content_cleaned = content.replace(hint, "").strip()
            if content_cleaned:
                all_contents.append(content_cleaned)
        
        # Collect images from each message
        msg_images = msg.get("images")
        if msg_images:
            all_images.append(msg_images)
    
    # Merge content and ensure thinking hint appears only once at the end
    merged_content = "\n\n".join(all_contents)
    # Check if any of the original messages had the hint (indicating thinking was enabled)
    had_thinking_hint = any(hint in msg.get("content", "") for msg in messages)
    if had_thinking_hint:
        merged_content = _append_thinking_hint(merged_content, hint)
    
    result = {
        "content": merged_content,
        "userInputMessageContext": base_context or {},
        "origin": base_origin or "KIRO_CLI",
        "modelId": base_model
    }
    
    # Add merged toolResults if any
    if all_tool_results:
        result["userInputMessageContext"]["toolResults"] = all_tool_results
    
    # Only keep images from the last 2 messages that have images
    if all_images:
        kept_images = []
        for img_list in all_images[-2:]:  # Take last 2 messages' images
            kept_images.extend(img_list)
        if kept_images:
            result["images"] = kept_images
    
    return result

def process_history(messages: List[ClaudeMessage], thinking_enabled: bool = False, hint: str = THINKING_HINT) -> List[Dict[str, Any]]:
    """Process history messages to match Amazon Q format (alternating user/assistant).
    
    Dual-mode detection:
    - If messages already alternate correctly (no consecutive user/assistant), skip merging
    - If messages have consecutive same-role messages, apply merge logic
    """
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
                            
                            # Check if there's actual content
                            if not any(i.get("text", "").strip() for i in aq_content):
                                # Use different message based on status
                                if block.get("status") != "error" and not block.get("is_error"):
                                    aq_content = [{"text": "Command executed successfully"}]
                                else:
                                    aq_content = [{"text": "Tool use was cancelled by the user"}]

                            # Determine status: check both 'status' field and 'is_error' flag
                            status = block.get("status")
                            if not status:
                                # If status not set, infer from is_error flag
                                status = "error" if block.get("is_error") else "success"

                            # Merge if exists
                            existing = next((r for r in tool_results if r["toolUseId"] == tool_use_id), None)
                            if existing:
                                existing["content"].extend(aq_content)
                                # Update status if this is an error
                                if status == "error":
                                    existing["status"] = "error"
                            else:
                                tool_results.append({
                                    "toolUseId": tool_use_id,
                                    "content": aq_content,
                                    "status": status
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
                "origin": "KIRO_CLI"
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

    # Dual-mode detection: check if messages already alternate correctly
    has_consecutive_same_role = False
    prev_role = None
    for item in raw_history:
        current_role = "user" if "userInputMessage" in item else "assistant"
        if prev_role == current_role:
            has_consecutive_same_role = True
            break
        prev_role = current_role
    
    # If messages already alternate, skip merging (fast path)
    if not has_consecutive_same_role:
        logger.info("Messages already alternate correctly, skipping merge logic")
        return raw_history

    # Second pass: merge consecutive user messages (only if needed)
    logger.info("Detected consecutive same-role messages, applying merge logic")
    pending_user_msgs = []
    for item in raw_history:
        if "userInputMessage" in item:
            pending_user_msgs.append(item["userInputMessage"])
        elif "assistantResponseMessage" in item:
            if pending_user_msgs:
                merged = merge_user_messages(pending_user_msgs, hint)
                history.append({"userInputMessage": merged})
                pending_user_msgs = []
            history.append(item)
            
    if pending_user_msgs:
        merged = merge_user_messages(pending_user_msgs, hint)
        history.append({"userInputMessage": merged})
        
    return history

def _detect_tool_call_loop(messages: List[ClaudeMessage], threshold: int = 3) -> Optional[str]:
    """Detect if the same tool is being called repeatedly (potential infinite loop).

    Only triggers if:
    1. Same tool called N times with same input
    2. All calls are in CONSECUTIVE assistant messages (no user messages between them)
    """
    recent_tool_calls = []
    consecutive_count = 0
    last_tool_call = None

    for msg in messages[-10:]:  # Check last 10 messages
        if msg.role == "assistant" and isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_name = block.get("name")
                    tool_input = json.dumps(block.get("input", {}), sort_keys=True)
                    current_call = (tool_name, tool_input)

                    if current_call == last_tool_call:
                        consecutive_count += 1
                    else:
                        consecutive_count = 1
                        last_tool_call = current_call

                    recent_tool_calls.append(current_call)
        elif msg.role == "user":
            # User message breaks the consecutive chain
            consecutive_count = 0
            last_tool_call = None

    # Only trigger if we have consecutive identical calls
    if consecutive_count >= threshold:
        return f"Detected infinite loop: tool '{last_tool_call[0]}' called {consecutive_count} times consecutively with same input"

    return None

def convert_claude_to_amazonq_request(req: ClaudeRequest, conversation_id: Optional[str] = None) -> Dict[str, Any]:
    """Convert ClaudeRequest to Amazon Q request body."""
    if conversation_id is None:
        conversation_id = str(uuid.uuid4())

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
                                    
                        # Check if there's actual content
                        if not any(i.get("text", "").strip() for i in aq_content):
                            # Use different message based on status
                            if block.get("status") != "error" and not block.get("is_error"):
                                aq_content = [{"text": "Command executed successfully"}]
                            else:
                                aq_content = [{"text": "Tool use was cancelled by the user"}]

                        # Determine status: check both 'status' field and 'is_error' flag
                        status = block.get("status")
                        if not status:
                            # If status not set, infer from is_error flag
                            status = "error" if block.get("is_error") else "success"

                        existing = next((r for r in tool_results if r["toolUseId"] == tid), None)
                        if existing:
                            existing["content"].extend(aq_content)
                            # Update status if this is an error
                            if status == "error":
                                existing["status"] = "error"
                        else:
                            tool_results.append({
                                "toolUseId": tid,
                                "content": aq_content,
                                "status": status
                            })
            prompt_content = "\n".join(text_parts)
        else:
            prompt_content = extract_text_from_content(content)

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

    # Append thinking hint at the very end, outside all structured blocks
    if thinking_enabled:
        formatted_content = _append_thinking_hint(formatted_content)

    # 5. Model
    model_id = map_model_name(req.model)

    # 6. User Input Message
    user_input_msg = {
        "content": formatted_content,
        "userInputMessageContext": user_ctx,
        "origin": "KIRO_CLI",
        "modelId": model_id
    }
    if images:
        user_input_msg["images"] = images
        
    # 7. History
    history_msgs = req.messages[:-1] if len(req.messages) > 1 else []
    aq_history = process_history(history_msgs, thinking_enabled=thinking_enabled, hint=THINKING_HINT)
    
    # 8. Final Body
    return {
        "conversationState": {
            "conversationId": conversation_id,
            "history": aq_history,
            "currentMessage": {
                "userInputMessage": user_input_msg
            },
            "chatTriggerType": "MANUAL"
        }
    }
