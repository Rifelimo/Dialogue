#!/usr/bin/env python3
"""
Versão de debug do servidor com logging extra.
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn

import sys
sys.path.insert(0, str(Path(__file__).parent))

from models import Message, MessageCreate, MessageType, Agent, AgentStatus, Thread, WebSocketMessage
from storage import Storage


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, agent_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[agent_id] = websocket
        print(f"[WS] {agent_id} conectou. Total: {len(self.active_connections)}")
    
    async def disconnect(self, agent_id: str):
        self.active_connections.pop(agent_id, None)
        print(f"[WS] {agent_id} desconectou. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: WebSocketMessage):
        print(f"[WS] Broadcasting para {len(self.active_connections)} conexões: {list(self.active_connections.keys())}")
        dead = []
        for agent_id, ws in self.active_connections.items():
            try:
                await ws.send_json(message.model_dump())
                print(f"[WS] Enviado para {agent_id}")
            except Exception as e:
                print(f"[WS] Erro ao enviar para {agent_id}: {e}")
                dead.append(agent_id)
        for agent_id in dead:
            self.active_connections.pop(agent_id, None)


storage: Optional[Storage] = None
manager = ConnectionManager()

app = FastAPI(title="Collab Server Debug")


@app.on_event("startup")
async def startup():
    global storage
    db_path = Path(__file__).parent / "collab.db"
    storage = Storage(str(db_path))
    storage.save_agent(Agent(
        id="user", name="Utilizador", status=AgentStatus.ONLINE,
        capabilities=["orchestrate", "approve", "direct"]
    ))
    print("[SERVER] Iniciado!")


@app.get("/")
async def dashboard():
    return FileResponse(Path(__file__).parent / "static" / "dashboard.html")


@app.get("/api/debug")
async def debug():
    return {"connections": list(manager.active_connections.keys())}


@app.post("/api/send")
async def send_message(msg: MessageCreate):
    print(f"[API] Mensagem de {msg.from_agent}: {msg.content[:50]}")
    
    message = Message(
        id=str(uuid4()),
        **{"from": msg.from_agent},
        **{"to": msg.to_agent},
        type=msg.type,
        content=msg.content,
        thread_id=msg.thread_id,
        metadata=msg.metadata,
        timestamp=datetime.utcnow()
    )
    storage.save_message(message)
    
    ws_msg = WebSocketMessage(
        event="new_message",
        data=message.model_dump(by_alias=True)
    )
    
    await manager.broadcast(ws_msg)
    
    return {"status": "sent", "message_id": message.id}


@app.get("/api/messages")
async def get_messages(limit: int = Query(default=100, le=500)):
    messages = storage.get_messages(limit=limit)
    return {"messages": [m.model_dump(by_alias=True) for m in messages]}


@app.get("/api/agents")
async def list_agents():
    agents = storage.get_agents()
    return {"agents": [a.model_dump() for a in agents]}


@app.post("/api/agents/register")
async def register_agent(agent: Agent):
    agent.status = AgentStatus.ONLINE
    agent.last_seen = datetime.utcnow()
    storage.save_agent(agent)
    return {"status": "registered"}


@app.post("/api/clear")
async def clear_all():
    storage.clear_all()
    return {"status": "cleared"}


@app.websocket("/ws/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
    await manager.connect(agent_id, websocket)
    
    await manager.broadcast(WebSocketMessage(
        event="agent_joined",
        data={"agent_id": agent_id}
    ))
    
    try:
        while True:
            data = await websocket.receive_json()
            print(f"[WS] Recebi de {agent_id}: {data}")
            
            if data.get("event") == "send":
                msg_data = data.get("data", {})
                message = Message(
                    id=str(uuid4()),
                    **{"from": agent_id},
                    **{"to": msg_data.get("to", "all")},
                    content=msg_data.get("content", ""),
                    type=MessageType(msg_data.get("type", "chat")),
                    timestamp=datetime.utcnow()
                )
                storage.save_message(message)
                
                await manager.broadcast(WebSocketMessage(
                    event="new_message",
                    data=message.model_dump(by_alias=True)
                ))
                
    except WebSocketDisconnect:
        await manager.disconnect(agent_id)
        await manager.broadcast(WebSocketMessage(
            event="agent_left",
            data={"agent_id": agent_id}
        ))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9999, log_level="info")
