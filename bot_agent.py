#!/usr/bin/env python3
"""
Bot agente que responde automaticamente a mensagens.
Uso: python bot_agent.py --name claude --style helpful
      python bot_agent.py --name codex --style technical
"""
import argparse
import asyncio
import json
import httpx
import websockets

RESPONSES = {
    "claude": {
        "greeting": "Olá! Sou o Claude Code. Como posso ajudar?",
        "default": "Entendido. Estou a analisar o que disseste.",
        "task": "Vou trabalhar nisso. Dá-me um momento.",
        "question": "Boa pergunta. Deixa-me pensar..."
    },
    "codex": {
        "greeting": "Hey! Codex aqui. Pronto para programar.",
        "default": "OK, estou a processar isso.",
        "task": "A implementar... vou mostrar o código em breve.",
        "question": "Interessante. Vou investigar."
    }
}

def get_response(agent_name: str, message: str, msg_type: str) -> str:
    responses = RESPONSES.get(agent_name, RESPONSES["claude"])
    
    lower_msg = message.lower()
    if any(g in lower_msg for g in ["olá", "ola", "hey", "oi", "bom dia", "boa tarde"]):
        return responses["greeting"]
    elif msg_type == "task":
        return responses["task"]
    elif msg_type == "question" or "?" in message:
        return responses["question"]
    else:
        return responses["default"]

async def run_bot(agent_name: str):
    uri = f"ws://localhost:9999/ws/{agent_name}"
    api_url = "http://localhost:9999/api"
    
    # Registar agente
    async with httpx.AsyncClient() as client:
        await client.post(f"{api_url}/agents/register", json={
            "id": agent_name,
            "name": f"{agent_name.title()} Bot",
            "capabilities": ["chat", "code", "review"]
        })
    
    print(f"[{agent_name}] A ligar ao servidor...")
    
    async with websockets.connect(uri) as ws:
        print(f"[{agent_name}] Online e a ouvir!")
        
        while True:
            try:
                data = await ws.recv()
                msg = json.loads(data)
                
                if msg.get("event") == "new_message":
                    m = msg["data"]
                    sender = m["from"]
                    content = m["content"]
                    msg_type = m.get("type", "chat")
                    to = m.get("to", "all")
                    
                    # Ignorar próprias mensagens e mensagens de sistema
                    if sender == agent_name or sender == "system":
                        continue
                    
                    # Responder se for para mim ou para todos
                    if to == "all" or to == agent_name:
                        print(f"[{agent_name}] Recebi de [{sender}]: {content}")
                        
                        # Pequeno delay para parecer mais natural
                        await asyncio.sleep(1)
                        
                        response = get_response(agent_name, content, msg_type)
                        
                        async with httpx.AsyncClient() as client:
                            await client.post(f"{api_url}/send", json={
                                "from": agent_name,
                                "to": sender if sender != "user" else "all",
                                "type": "chat",
                                "content": response
                            })
                        
                        print(f"[{agent_name}] Respondi: {response}")
                        
            except websockets.exceptions.ConnectionClosed:
                print(f"[{agent_name}] Conexão perdida. A reconectar...")
                await asyncio.sleep(2)
                break
            except Exception as e:
                print(f"[{agent_name}] Erro: {e}")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="claude", help="Nome do agente")
    args = parser.parse_args()
    
    while True:
        try:
            await run_bot(args.name)
        except Exception as e:
            print(f"Erro: {e}. A reconectar em 3s...")
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
