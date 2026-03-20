#!/usr/bin/env python3
"""
Servidor híbrido de colaboração entre agentes.

Suporta três interfaces simultaneamente:
1. MCP (stdin/stdout) - para Claude Code
2. HTTP REST - para qualquer CLI (curl)
3. WebSocket - para notificações em tempo real

Uso:
    # Modo HTTP/WebSocket (standalone)
    python server.py --port 9999

    # Modo MCP (para integração com Claude Code)
    python server.py --mcp

    # Modo dual (ambos simultaneamente)
    python server.py --port 9999 --mcp
"""

import argparse
import asyncio
import json
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Adicionar o diretório atual ao path para imports locais
sys.path.insert(0, str(Path(__file__).parent))

from models import Message, MessageCreate, MessageType, Agent, AgentStatus, Thread, WebSocketMessage
from storage import Storage


# --- Gestão de conexões WebSocket ---

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.lock = asyncio.Lock()

    async def connect(self, agent_id: str, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.active_connections[agent_id] = websocket

    async def disconnect(self, agent_id: str):
        async with self.lock:
            self.active_connections.pop(agent_id, None)

    async def broadcast(self, message: WebSocketMessage):
        async with self.lock:
            dead_connections = []
            for agent_id, ws in self.active_connections.items():
                try:
                    await ws.send_json(message.model_dump())
                except Exception:
                    dead_connections.append(agent_id)
            for agent_id in dead_connections:
                self.active_connections.pop(agent_id, None)

    async def send_to(self, agent_id: str, message: WebSocketMessage):
        async with self.lock:
            if agent_id in self.active_connections:
                try:
                    await self.active_connections[agent_id].send_json(message.model_dump())
                except Exception:
                    self.active_connections.pop(agent_id, None)


# --- Globals ---

storage: Optional[Storage] = None
manager = ConnectionManager()


# --- FastAPI app ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    global storage
    db_path = Path(__file__).parent / "collab.db"
    storage = Storage(str(db_path))
    
    # Registar o utilizador como agente especial
    storage.save_agent(Agent(
        id="user",
        name="Utilizador",
        status=AgentStatus.ONLINE,
        capabilities=["orchestrate", "approve", "direct"]
    ))
    
    yield
    
    if storage:
        storage.close()


app = FastAPI(
    title="Collab Server",
    description="Servidor de colaboração entre agentes CLI",
    version="1.0.0",
    lifespan=lifespan
)


# --- REST API ---

@app.get("/")
async def dashboard():
    """Serve o dashboard web."""
    dashboard_path = Path(__file__).parent / "static" / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(dashboard_path)
    return HTMLResponse("<h1>Dashboard em construção</h1>")


@app.post("/api/send")
async def send_message(msg: MessageCreate):
    """Envia uma mensagem."""
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
    
    # Notificar via WebSocket
    ws_msg = WebSocketMessage(
        event="new_message",
        data=message.model_dump(by_alias=True)
    )
    
    if message.to_agent == "all":
        await manager.broadcast(ws_msg)
    else:
        await manager.send_to(message.to_agent, ws_msg)
        # Também enviar ao remetente para confirmar
        await manager.send_to(message.from_agent, ws_msg)
        # E ao utilizador para ver tudo
        await manager.send_to("user", ws_msg)
    
    return {"status": "sent", "message_id": message.id}


@app.get("/api/messages")
async def get_messages(
    thread_id: Optional[str] = None,
    to: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = Query(default=100, le=500)
):
    """Lista mensagens com filtros opcionais."""
    since_dt = datetime.fromisoformat(since) if since else None
    messages = storage.get_messages(
        thread_id=thread_id,
        to_agent=to,
        since=since_dt,
        limit=limit
    )
    return {"messages": [m.model_dump(by_alias=True) for m in messages]}


@app.get("/api/messages/{message_id}")
async def get_message(message_id: str):
    """Obtém uma mensagem específica."""
    message = storage.get_message(message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message.model_dump(by_alias=True)


@app.delete("/api/messages/{message_id}")
async def delete_message(message_id: str):
    """Apaga uma mensagem."""
    if storage.delete_message(message_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Message not found")


@app.post("/api/messages/{message_id}/read")
async def mark_as_read(message_id: str, agent_id: str):
    """Marca uma mensagem como lida por um agente."""
    if storage.mark_as_read(message_id, agent_id):
        return {"status": "marked"}
    raise HTTPException(status_code=404, detail="Message not found")


@app.get("/api/agents")
async def list_agents():
    """Lista agentes registados."""
    agents = storage.get_agents()
    return {"agents": [a.model_dump() for a in agents]}


@app.post("/api/agents/register")
async def register_agent(agent: Agent):
    """Regista ou atualiza um agente."""
    agent.status = AgentStatus.ONLINE
    agent.last_seen = datetime.utcnow()
    storage.save_agent(agent)
    
    # Notificar outros
    await manager.broadcast(WebSocketMessage(
        event="agent_joined",
        data={"agent_id": agent.id, "name": agent.name}
    ))
    
    return {"status": "registered"}


@app.post("/api/agents/{agent_id}/status")
async def update_agent_status(agent_id: str, status: AgentStatus):
    """Atualiza o status de um agente."""
    if storage.update_agent_status(agent_id, status):
        return {"status": "updated"}
    raise HTTPException(status_code=404, detail="Agent not found")


@app.get("/api/threads")
async def list_threads():
    """Lista threads de conversa."""
    threads = storage.get_threads()
    return {"threads": [t.model_dump() for t in threads]}


@app.post("/api/threads")
async def create_thread(thread: Thread):
    """Cria uma nova thread."""
    storage.save_thread(thread)
    return {"status": "created", "thread_id": thread.id}


@app.get("/api/unread/{agent_id}")
async def get_unread_count(agent_id: str):
    """Conta mensagens não lidas para um agente."""
    count = storage.get_unread_count(agent_id)
    return {"unread": count}


@app.post("/api/clear")
async def clear_all():
    """Limpa todas as mensagens e threads (reset)."""
    storage.clear_all()
    return {"status": "cleared"}


# --- WebSocket ---

@app.websocket("/ws/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
    """WebSocket para notificações em tempo real."""
    await manager.connect(agent_id, websocket)
    
    # Atualizar status do agente
    agent = storage.get_agent(agent_id)
    if agent:
        storage.update_agent_status(agent_id, AgentStatus.ONLINE)
    
    # Notificar outros
    await manager.broadcast(WebSocketMessage(
        event="agent_joined",
        data={"agent_id": agent_id}
    ))
    
    try:
        while True:
            data = await websocket.receive_json()
            
            # Processar eventos do cliente
            if data.get("event") == "typing":
                await manager.broadcast(WebSocketMessage(
                    event="typing",
                    data={"agent_id": agent_id}
                ))
            elif data.get("event") == "send":
                # Enviar mensagem via WebSocket
                msg_data = data.get("data", {})
                msg = MessageCreate(
                    **{"from": agent_id},
                    **{"to": msg_data.get("to", "all")},
                    content=msg_data.get("content", ""),
                    type=MessageType(msg_data.get("type", "chat")),
                    thread_id=msg_data.get("thread_id")
                )
                # Reutilizar lógica do REST
                message = Message(
                    id=str(uuid4()),
                    **{"from": msg.from_agent},
                    **{"to": msg.to_agent},
                    type=msg.type,
                    content=msg.content,
                    thread_id=msg.thread_id,
                    timestamp=datetime.utcnow()
                )
                storage.save_message(message)
                
                ws_msg = WebSocketMessage(
                    event="new_message",
                    data=message.model_dump(by_alias=True)
                )
                await manager.broadcast(ws_msg)
                
    except WebSocketDisconnect:
        await manager.disconnect(agent_id)
        if agent:
            storage.update_agent_status(agent_id, AgentStatus.OFFLINE)
        await manager.broadcast(WebSocketMessage(
            event="agent_left",
            data={"agent_id": agent_id}
        ))


# --- MCP Handler ---

class MCPHandler:
    """Handler para protocolo MCP via stdin/stdout."""
    
    def __init__(self, storage: Storage):
        self.storage = storage
        self.tools = {
            "collab_send": self.tool_send,
            "collab_read": self.tool_read,
            "collab_agents": self.tool_agents,
            "collab_unread": self.tool_unread,
            "collab_register": self.tool_register,
        }
    
    async def tool_send(self, params: dict) -> dict:
        """Envia uma mensagem."""
        message = Message(
            id=str(uuid4()),
            **{"from": params.get("from", "claude")},
            **{"to": params.get("to", "all")},
            type=MessageType(params.get("type", "chat")),
            content=params["content"],
            thread_id=params.get("thread_id"),
            timestamp=datetime.utcnow()
        )
        self.storage.save_message(message)
        return {"status": "sent", "message_id": message.id}
    
    async def tool_read(self, params: dict) -> dict:
        """Lê mensagens."""
        messages = self.storage.get_messages(
            to_agent=params.get("to"),
            thread_id=params.get("thread_id"),
            limit=params.get("limit", 20)
        )
        return {
            "messages": [
                {
                    "id": m.id,
                    "from": m.from_agent,
                    "to": m.to_agent,
                    "content": m.content,
                    "type": m.type.value,
                    "timestamp": m.timestamp.isoformat()
                }
                for m in messages
            ]
        }
    
    async def tool_agents(self, params: dict) -> dict:
        """Lista agentes."""
        agents = self.storage.get_agents()
        return {
            "agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "status": a.status.value
                }
                for a in agents
            ]
        }
    
    async def tool_unread(self, params: dict) -> dict:
        """Conta mensagens não lidas."""
        agent_id = params.get("agent_id", "claude")
        count = self.storage.get_unread_count(agent_id)
        return {"unread": count}
    
    async def tool_register(self, params: dict) -> dict:
        """Regista um agente."""
        agent = Agent(
            id=params["id"],
            name=params.get("name", params["id"]),
            status=AgentStatus.ONLINE,
            capabilities=params.get("capabilities", [])
        )
        self.storage.save_agent(agent)
        return {"status": "registered"}
    
    def get_tools_schema(self) -> list[dict]:
        """Retorna o schema das tools para MCP."""
        return [
            {
                "name": "collab_send",
                "description": "Envia uma mensagem para outro agente ou para todos",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Conteúdo da mensagem"},
                        "to": {"type": "string", "description": "Destinatário (agent_id ou 'all')", "default": "all"},
                        "from": {"type": "string", "description": "Remetente", "default": "claude"},
                        "type": {"type": "string", "enum": ["chat", "task", "code", "review", "question"], "default": "chat"},
                        "thread_id": {"type": "string", "description": "ID da thread (opcional)"}
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "collab_read",
                "description": "Lê mensagens recentes",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Filtrar por destinatário"},
                        "thread_id": {"type": "string", "description": "Filtrar por thread"},
                        "limit": {"type": "integer", "description": "Número máximo de mensagens", "default": 20}
                    }
                }
            },
            {
                "name": "collab_agents",
                "description": "Lista agentes registados e o seu estado",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "collab_unread",
                "description": "Conta mensagens não lidas",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string", "description": "ID do agente", "default": "claude"}
                    }
                }
            },
            {
                "name": "collab_register",
                "description": "Regista este agente no servidor",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "ID único do agente"},
                        "name": {"type": "string", "description": "Nome do agente"},
                        "capabilities": {"type": "array", "items": {"type": "string"}, "description": "Capacidades do agente"}
                    },
                    "required": ["id"]
                }
            }
        ]
    
    async def handle_request(self, request: dict) -> dict:
        """Processa um request MCP."""
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params", {})
        
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "collab-server", "version": "1.0.0"}
                }
            }
        
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.get_tools_schema()}
            }
        
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            
            if tool_name in self.tools:
                try:
                    result = await self.tools[tool_name](tool_args)
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
                        }
                    }
                except Exception as e:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32000, "message": str(e)}
                    }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}
                }
        
        elif method == "notifications/initialized":
            # Notificação, não precisa de resposta
            return None
        
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            }
    
    async def run(self):
        """Loop principal do MCP."""
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                
                request = json.loads(line.strip())
                response = await self.handle_request(request)
                
                if response:
                    print(json.dumps(response), flush=True)
                    
            except json.JSONDecodeError:
                continue
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"}
                }
                print(json.dumps(error_response), flush=True)


# --- Main ---

def run_http_server(port: int):
    """Corre o servidor HTTP/WebSocket."""
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


async def run_mcp_server():
    """Corre o servidor MCP."""
    global storage
    db_path = Path(__file__).parent / "collab.db"
    storage = Storage(str(db_path))
    
    handler = MCPHandler(storage)
    await handler.run()


def main():
    parser = argparse.ArgumentParser(description="Servidor de colaboração híbrido")
    parser.add_argument("--port", type=int, default=9999, help="Porta HTTP/WebSocket")
    parser.add_argument("--mcp", action="store_true", help="Modo MCP (stdin/stdout)")
    args = parser.parse_args()
    
    if args.mcp and not sys.stdin.isatty():
        # Modo MCP puro
        asyncio.run(run_mcp_server())
    elif args.mcp:
        # Modo dual: HTTP + MCP em threads separadas
        http_thread = threading.Thread(target=run_http_server, args=(args.port,), daemon=True)
        http_thread.start()
        asyncio.run(run_mcp_server())
    else:
        # Modo HTTP puro
        run_http_server(args.port)


if __name__ == "__main__":
    main()
