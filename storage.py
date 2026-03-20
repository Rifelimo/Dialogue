"""
Storage SQLite para persistência de mensagens e agentes.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from models import Agent, AgentStatus, Message, MessageType, Thread


class Storage:
    def __init__(self, db_path: str = "collab.db"):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        """Cria as tabelas se não existirem."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                thread_id TEXT,
                metadata TEXT,
                read_by TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                capabilities TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                participants TEXT,
                metadata TEXT
            )
        """)
        
        # Índices para queries comuns
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_agent)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
        
        self.conn.commit()

    # --- Messages ---

    def save_message(self, message: Message) -> Message:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO messages (id, from_agent, to_agent, type, content, timestamp, thread_id, metadata, read_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message.id,
            message.from_agent,
            message.to_agent,
            message.type.value,
            message.content,
            message.timestamp.isoformat(),
            message.thread_id,
            json.dumps(message.metadata),
            json.dumps(message.read_by)
        ))
        self.conn.commit()
        return message

    def get_messages(
        self,
        thread_id: Optional[str] = None,
        to_agent: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> list[Message]:
        cursor = self.conn.cursor()
        
        query = "SELECT * FROM messages WHERE 1=1"
        params = []
        
        if thread_id:
            query += " AND thread_id = ?"
            params.append(thread_id)
        
        if to_agent:
            query += " AND (to_agent = ? OR to_agent = 'all')"
            params.append(to_agent)
        
        if since:
            query += " AND timestamp > ?"
            params.append(since.isoformat())
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        messages = []
        for row in rows:
            messages.append(Message(
                id=row["id"],
                **{"from": row["from_agent"]},
                **{"to": row["to_agent"]},
                type=MessageType(row["type"]),
                content=row["content"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                thread_id=row["thread_id"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                read_by=json.loads(row["read_by"]) if row["read_by"] else []
            ))
        
        return list(reversed(messages))  # Ordem cronológica

    def get_message(self, message_id: str) -> Optional[Message]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return Message(
            id=row["id"],
            **{"from": row["from_agent"]},
            **{"to": row["to_agent"]},
            type=MessageType(row["type"]),
            content=row["content"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            thread_id=row["thread_id"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            read_by=json.loads(row["read_by"]) if row["read_by"] else []
        )

    def delete_message(self, message_id: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_as_read(self, message_id: str, agent_id: str) -> bool:
        message = self.get_message(message_id)
        if not message:
            return False
        
        if agent_id not in message.read_by:
            message.read_by.append(agent_id)
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE messages SET read_by = ? WHERE id = ?",
                (json.dumps(message.read_by), message_id)
            )
            self.conn.commit()
        
        return True

    def get_unread_count(self, agent_id: str) -> int:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM messages 
            WHERE (to_agent = ? OR to_agent = 'all')
            AND read_by NOT LIKE ?
        """, (agent_id, f'%"{agent_id}"%'))
        return cursor.fetchone()[0]

    # --- Agents ---

    def save_agent(self, agent: Agent) -> Agent:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO agents (id, name, status, last_seen, capabilities)
            VALUES (?, ?, ?, ?, ?)
        """, (
            agent.id,
            agent.name,
            agent.status.value,
            agent.last_seen.isoformat(),
            json.dumps(agent.capabilities)
        ))
        self.conn.commit()
        return agent

    def get_agents(self) -> list[Agent]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM agents")
        rows = cursor.fetchall()
        
        return [
            Agent(
                id=row["id"],
                name=row["name"],
                status=AgentStatus(row["status"]),
                last_seen=datetime.fromisoformat(row["last_seen"]),
                capabilities=json.loads(row["capabilities"]) if row["capabilities"] else []
            )
            for row in rows
        ]

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return Agent(
            id=row["id"],
            name=row["name"],
            status=AgentStatus(row["status"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
            capabilities=json.loads(row["capabilities"]) if row["capabilities"] else []
        )

    def update_agent_status(self, agent_id: str, status: AgentStatus) -> bool:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE agents SET status = ?, last_seen = ? WHERE id = ?",
            (status.value, datetime.utcnow().isoformat(), agent_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # --- Threads ---

    def save_thread(self, thread: Thread) -> Thread:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO threads (id, title, created_at, participants, metadata)
            VALUES (?, ?, ?, ?, ?)
        """, (
            thread.id,
            thread.title,
            thread.created_at.isoformat(),
            json.dumps(thread.participants),
            json.dumps(thread.metadata)
        ))
        self.conn.commit()
        return thread

    def get_threads(self) -> list[Thread]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM threads ORDER BY created_at DESC")
        rows = cursor.fetchall()
        
        return [
            Thread(
                id=row["id"],
                title=row["title"],
                created_at=datetime.fromisoformat(row["created_at"]),
                participants=json.loads(row["participants"]) if row["participants"] else [],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {}
            )
            for row in rows
        ]

    def get_thread(self, thread_id: str) -> Optional[Thread]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM threads WHERE id = ?", (thread_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return Thread(
            id=row["id"],
            title=row["title"],
            created_at=datetime.fromisoformat(row["created_at"]),
            participants=json.loads(row["participants"]) if row["participants"] else [],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {}
        )

    def clear_all(self):
        """Limpa todas as mensagens e threads (útil para reset)."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM messages")
        cursor.execute("DELETE FROM threads")
        self.conn.commit()

    def close(self):
        self.conn.close()
