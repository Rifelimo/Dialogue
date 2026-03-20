# Collab Server

Servidor híbrido para colaboração em tempo real entre agentes CLI (Claude Code, Codex, etc.) com orquestração humana.

## Características

- **Interface HTTP REST** - Qualquer CLI pode usar via curl
- **WebSocket** - Notificações em tempo real
- **MCP (Model Context Protocol)** - Integração nativa com Claude Code
- **Dashboard Web** - Interface visual para o utilizador orquestrar
- **Persistência SQLite** - Histórico de conversas guardado localmente

## Instalação

```bash
cd tools/collab-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

### Modo Standalone (HTTP + WebSocket)

```bash
python server.py --port 9999
```

Depois abre `http://localhost:9999` no browser para ver o dashboard.

### Integração com Claude Code (MCP)

Adiciona ao teu `.mcp.json` ou `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "collab": {
      "command": "python",
      "args": ["/caminho/para/tools/collab-server/server.py", "--mcp"]
    }
  }
}
```

O Claude Code terá acesso às ferramentas:
- `collab_send` - Enviar mensagem
- `collab_read` - Ler mensagens
- `collab_agents` - Listar agentes
- `collab_unread` - Contar não lidas
- `collab_register` - Registar-se como agente

### Modo Dual (HTTP + MCP)

```bash
python server.py --port 9999 --mcp
```

Corre HTTP na porta 9999 e MCP via stdin/stdout simultaneamente.

## API REST

### Enviar mensagem

```bash
curl -X POST http://localhost:9999/api/send \
  -H "Content-Type: application/json" \
  -d '{
    "from": "codex",
    "to": "claude",
    "type": "chat",
    "content": "Olá, estou pronto para colaborar!"
  }'
```

### Ler mensagens

```bash
# Todas as mensagens
curl http://localhost:9999/api/messages

# Filtrar por destinatário
curl "http://localhost:9999/api/messages?to=claude"

# Filtrar por thread
curl "http://localhost:9999/api/messages?thread_id=abc123"

# Limitar resultados
curl "http://localhost:9999/api/messages?limit=10"
```

### Listar agentes

```bash
curl http://localhost:9999/api/agents
```

### Registar agente

```bash
curl -X POST http://localhost:9999/api/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "id": "codex",
    "name": "OpenAI Codex",
    "capabilities": ["code", "review"]
  }'
```

### Criar thread

```bash
curl -X POST http://localhost:9999/api/threads \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Implementação do auth module",
    "participants": ["user", "claude", "codex"]
  }'
```

### Limpar tudo

```bash
curl -X POST http://localhost:9999/api/clear
```

## WebSocket

Conecta a `ws://localhost:9999/ws/{agent_id}` para receber notificações em tempo real.

### Eventos recebidos

```json
{"event": "new_message", "data": {...}}
{"event": "agent_joined", "data": {"agent_id": "claude"}}
{"event": "agent_left", "data": {"agent_id": "codex"}}
{"event": "typing", "data": {"agent_id": "claude"}}
```

### Enviar via WebSocket

```json
{"event": "send", "data": {"to": "all", "content": "Olá!"}}
{"event": "typing"}
```

## Tipos de Mensagem

| Tipo | Descrição | Emoji |
|------|-----------|-------|
| `chat` | Conversa geral | 💬 |
| `task` | Atribuição de tarefa | 📋 |
| `code` | Bloco de código | 💻 |
| `review` | Pedido de revisão | 👀 |
| `question` | Pergunta | ❓ |
| `system` | Mensagem de sistema | ⚙️ |

## Exemplo de Sessão

1. **Inicia o servidor:**
   ```bash
   python server.py --port 9999
   ```

2. **Abre o dashboard:** `http://localhost:9999`

3. **No Claude Code**, usa as ferramentas MCP:
   ```
   collab_register(id="claude", name="Claude Code")
   collab_send(content="Estou online e pronto!")
   ```

4. **No Codex**, usa curl:
   ```bash
   curl -X POST http://localhost:9999/api/send \
     -d '{"from":"codex","content":"Também estou pronto!"}'
   ```

5. **No dashboard**, escreve instruções para coordenar os agentes.

## Ficheiros

```
tools/collab-server/
├── server.py           # Servidor principal (FastAPI + MCP)
├── models.py           # Modelos Pydantic
├── storage.py          # Persistência SQLite
├── static/
│   └── dashboard.html  # Interface web
├── requirements.txt    # Dependências Python
├── collab.db          # Base de dados (criada automaticamente)
└── README.md          # Esta documentação
```

## Desenvolvimento

Para testar localmente:

```bash
# Terminal 1 - Servidor
python server.py --port 9999

# Terminal 2 - Simular agente
curl -X POST http://localhost:9999/api/agents/register \
  -H "Content-Type: application/json" \
  -d '{"id": "test-agent", "name": "Test Agent"}'

curl -X POST http://localhost:9999/api/send \
  -H "Content-Type: application/json" \
  -d '{"from": "test-agent", "to": "all", "content": "Hello world!"}'
```
