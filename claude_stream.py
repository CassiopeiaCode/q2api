import json
import logging
import importlib.util
from pathlib import Path
from typing import AsyncGenerator, Optional, Dict, Any, List, Set
import tiktoken

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Tokenizer
# ------------------------------------------------------------------------------

try:
    # cl100k_base is used by gpt-4, gpt-3.5-turbo, text-embedding-ada-002
    ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    ENCODING = None

def count_tokens(text: str) -> int:
    """Counts tokens with tiktoken."""
    if not text or not ENCODING:
        return 0
    return len(ENCODING.encode(text))

# ------------------------------------------------------------------------------
# Dynamic Loader
# ------------------------------------------------------------------------------

def _load_claude_parser():
    """Dynamically load claude_parser module."""
    base_dir = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("v2_claude_parser", str(base_dir / "claude_parser.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

try:
    _parser = _load_claude_parser()
    build_message_start = _parser.build_message_start
    build_content_block_start = _parser.build_content_block_start
    build_content_block_delta = _parser.build_content_block_delta
    build_content_block_stop = _parser.build_content_block_stop
    build_ping = _parser.build_ping
    build_message_stop = _parser.build_message_stop
    build_tool_use_start = _parser.build_tool_use_start
    build_tool_use_input_delta = _parser.build_tool_use_input_delta
    build_thinking_block_start = _parser.build_thinking_block_start
    build_thinking_delta = _parser.build_thinking_delta
except Exception as e:
    logger.error(f"Failed to load claude_parser: {e}")
    # Fallback definitions
    def build_message_start(*args, **kwargs): return ""
    def build_content_block_start(*args, **kwargs): return ""
    def build_content_block_delta(*args, **kwargs): return ""
    def build_content_block_stop(*args, **kwargs): return ""
    def build_ping(*args, **kwargs): return ""
    def build_message_stop(*args, **kwargs): return ""
    def build_tool_use_start(*args, **kwargs): return ""
    def build_tool_use_input_delta(*args, **kwargs): return ""
    def build_thinking_block_start(*args, **kwargs): return ""
    def build_thinking_delta(*args, **kwargs): return ""

class ClaudeStreamHandler:
    def __init__(self, model: str, input_tokens: int = 0):
        self.model = model
        self.input_tokens = input_tokens
        self.response_buffer: List[str] = []
        self.content_block_index: int = -1
        self.content_block_started: bool = False
        self.content_block_start_sent: bool = False
        self.content_block_stop_sent: bool = False
        self.message_start_sent: bool = False
        self.conversation_id: Optional[str] = None

        # Tool use state
        self.current_tool_use: Optional[Dict[str, Any]] = None
        self.tool_input_buffer: List[str] = []
        self.tool_use_id: Optional[str] = None
        self.tool_name: Optional[str] = None
        self._processed_tool_use_ids: Set[str] = set()
        self.all_tool_inputs: List[str] = []

        # Thinking state
        self.thinking_buffer: List[str] = []
        self.in_thinking_block: bool = False

    async def handle_event(self, event_type: str, payload: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Process a single Amazon Q event and yield Claude SSE events."""
        
        # 1. Message Start (initial-response)
        if event_type == "initial-response":
            if not self.message_start_sent:
                conv_id = payload.get('conversationId', self.conversation_id or 'unknown')
                self.conversation_id = conv_id
                yield build_message_start(conv_id, self.model, self.input_tokens)
                self.message_start_sent = True
                yield build_ping()

        # 2. Content Block Delta (assistantResponseEvent)
        elif event_type == "assistantResponseEvent":
            content = payload.get("content", "")

            # Check if this is thinking content (heuristic: starts with thinking markers)
            is_thinking = self._is_thinking_content(content, payload)

            # Close any open tool use block
            if self.current_tool_use and not self.content_block_stop_sent:
                yield build_content_block_stop(self.content_block_index)
                self.content_block_stop_sent = True
                self.current_tool_use = None

            # Handle thinking block
            if is_thinking:
                # Close text block if open
                if self.content_block_start_sent and not self.in_thinking_block and not self.content_block_stop_sent:
                    yield build_content_block_stop(self.content_block_index)
                    self.content_block_stop_sent = True

                # Start thinking block if needed
                if not self.in_thinking_block:
                    self.content_block_index += 1
                    yield build_thinking_block_start(self.content_block_index)
                    self.in_thinking_block = True
                    self.content_block_started = True
                    self.content_block_start_sent = True
                    self.content_block_stop_sent = False

                # Send thinking delta
                if content:
                    self.thinking_buffer.append(content)
                    yield build_thinking_delta(self.content_block_index, content)
            else:
                # Close thinking block if open
                if self.in_thinking_block and not self.content_block_stop_sent:
                    yield build_content_block_stop(self.content_block_index)
                    self.content_block_stop_sent = True
                    self.in_thinking_block = False

                # Start text content block if needed
                if not self.content_block_start_sent or self.in_thinking_block:
                    self.content_block_index += 1
                    yield build_content_block_start(self.content_block_index, "text")
                    self.content_block_start_sent = True
                    self.content_block_started = True
                    self.content_block_stop_sent = False

                # Send delta
                if content:
                    self.response_buffer.append(content)
                    yield build_content_block_delta(self.content_block_index, content)

        # 3. Tool Use (toolUseEvent)
        elif event_type == "toolUseEvent":
            tool_use_id = payload.get("toolUseId")
            tool_name = payload.get("name")
            tool_input = payload.get("input", {})
            is_stop = payload.get("stop", False)

            # Start new tool use
            if tool_use_id and tool_name and not self.current_tool_use:
                # Close previous text block if open
                if self.content_block_start_sent and not self.content_block_stop_sent:
                    yield build_content_block_stop(self.content_block_index)
                    self.content_block_stop_sent = True

                self._processed_tool_use_ids.add(tool_use_id)
                self.content_block_index += 1
                
                yield build_tool_use_start(self.content_block_index, tool_use_id, tool_name)
                
                self.content_block_started = True
                self.current_tool_use = {"toolUseId": tool_use_id, "name": tool_name}
                self.tool_use_id = tool_use_id
                self.tool_name = tool_name
                self.tool_input_buffer = []
                self.content_block_stop_sent = False
                self.content_block_start_sent = True

            # Accumulate input
            if self.current_tool_use and tool_input:
                fragment = ""
                if isinstance(tool_input, str):
                    fragment = tool_input
                else:
                    fragment = json.dumps(tool_input, ensure_ascii=False)
                
                self.tool_input_buffer.append(fragment)
                yield build_tool_use_input_delta(self.content_block_index, fragment)

            # Stop tool use
            if is_stop and self.current_tool_use:
                full_input = "".join(self.tool_input_buffer)
                self.all_tool_inputs.append(full_input)
                
                yield build_content_block_stop(self.content_block_index)
                self.content_block_stop_sent = True
                self.content_block_started = False
                self.current_tool_use = None
                self.tool_use_id = None
                self.tool_name = None
                self.tool_input_buffer = []

        # 4. Assistant Response End (assistantResponseEnd)
        elif event_type == "assistantResponseEnd":
            # Close any open block
            if self.content_block_started and not self.content_block_stop_sent:
                yield build_content_block_stop(self.content_block_index)
                self.content_block_stop_sent = True

    def _is_thinking_content(self, content: str, payload: Dict[str, Any]) -> bool:
        """Heuristic to detect if content is thinking."""
        # Check if already in thinking block
        if self.in_thinking_block:
            # Stay in thinking until we see clear end markers
            if content and any(marker in content.lower() for marker in ["</thinking>", "now i'll", "now i will", "let me proceed"]):
                return False
            return True

        # Check for thinking start markers
        if content:
            thinking_markers = ["<thinking>", "let me think", "i need to think", "thinking:", "my reasoning"]
            return any(marker in content.lower() for marker in thinking_markers)

        return False

    async def finish(self) -> AsyncGenerator[str, None]:
        """Send final events."""
        # Ensure last block is closed
        if self.content_block_started and not self.content_block_stop_sent:
            yield build_content_block_stop(self.content_block_index)
            self.content_block_stop_sent = True

        # Calculate output tokens (approximate)
        full_text = "".join(self.response_buffer)
        full_tool_input = "".join(self.all_tool_inputs)
        full_thinking = "".join(self.thinking_buffer)
        output_tokens = count_tokens(full_text) + count_tokens(full_tool_input) + count_tokens(full_thinking)

        yield build_message_stop(self.input_tokens, output_tokens, "end_turn")