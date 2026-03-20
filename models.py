"""
Modelos Pydantic para o servidor de colaboração.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    CHAT = "chat"
    TASK = "task"
    CODE = "code"
    REVIEW = "review"
    QUESTION = "question"
    SYSTEM = "system"


class AgentStatus(str, Enum):
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    from_agent: str = Field(..., alias="from")
    to_agent: str = Field(default="all", alias="to")
    type: MessageType = MessageType.CHAT
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    thread_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    read_by: list[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True


class MessageCreate(BaseModel):
    from_agent: str = Field(..., alias="from")
    to_agent: str = Field(default="all", alias="to")
    type: MessageType = MessageType.CHAT
    content: str
    thread_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

    class Config:
        populate_by_name = True


class Agent(BaseModel):
    id: str
    name: str
    status: AgentStatus = AgentStatus.OFFLINE
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    capabilities: list[str] = Field(default_factory=list)


class Thread(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    participants: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class WebSocketMessage(BaseModel):
    """Mensagem enviada via WebSocket."""
    event: str  # "new_message", "agent_joined", "agent_left", "typing"
    data: dict
