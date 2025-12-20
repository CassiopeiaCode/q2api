from typing import List, Optional, Union, Dict, Any, Literal
from pydantic import BaseModel, Field, AliasChoices

class ClaudeMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]

class ClaudeTool(BaseModel):
    name: str
    description: Optional[str] = ""
    input_schema: Dict[str, Any]

class ClaudeRequest(BaseModel):
    model: str
    messages: List[ClaudeMessage]
    max_tokens: int = 4096
    temperature: Optional[float] = None
    tools: Optional[List[ClaudeTool]] = None
    stream: bool = False
    system: Optional[Union[str, List[Dict[str, Any]]]] = None
    thinking: Optional[Dict[str, Any]] = None
    conversation_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("conversation_id", "conversationId")
    )
