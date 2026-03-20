#!/usr/bin/env python3
"""
Bot agente com comunicação inter-bots controlada pelo user.
"""
import argparse
import asyncio
import json
import sys
import httpx
import websockets

OTHER_BOT = {"claude": "codex", "codex": "claude"}

def parse_user_request(agent_name: str, message: str) -> tuple[str, str] | None:
    """Analisa se o user está a pedir algo a este agente."""
    lower = message.lower()
    other = OTHER_BOT.get(agent_name, "")
    
    # Verificar se a mensagem menciona ESTE agente primeiro
    my_pos = lower.find(agent_name)
    other_pos = lower.find(other)
    
    # Se o outro está mencionado primeiro, não sou eu que devo responder
    if other_pos != -1 and (my_pos == -1 or other_pos < my_pos):
        return None
    
    # Se sou mencionado e pedem para falar com o outro
    talk_words = ["diz", "fala", "pergunta", "pede", "conversa"]
    if my_pos != -1 and other in lower and any(w in lower for w in talk_words):
        if agent_name == "claude":
            return f"Codex, o user quer que discutamos isto. O que achas?", "codex"
        else:
            return f"Claude, o user quer a nossa opinião. Qual é a tua ideia?", "claude"
    
    # Saudação ou pergunta directa
    if any(g in lower for g in ["olá", "ola", "hey", "oi"]):
        return ("Olá! Claude aqui." if agent_name == "claude" else "Hey! Codex pronto."), "all"
    
    if "?" in message:
        return ("A analisar..." if agent_name == "claude" else "A verificar..."), "all"
    
    return None

def respond_to_bot(agent_name: str, sender: str, message: str) -> tuple[str, str]:
    """Responde a outro bot."""
    if agent_name == "claude":
        return "Concordo. Podemos avançar com essa abordagem.", "all"
    else:
        return "Boa ideia. Vou implementar isso.", "all"

async def run_bot(agent_name: str, api_url: str):
    uri = f"ws://localhost:9999/ws/{agent_name}"
    
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{api_url}/agents/register", json={
                "id": agent_name,
                "name": f"{agent_name.title()} Bot"
            })
    except Exception as e:
        print(f"[{agent_name}] Erro: {e}", file=sys.stderr)
        return
    
    print(f"[{agent_name}] Online!", file=sys.stderr)
    
    try:
        async with websockets.connect(uri) as ws:
            while True:
                try:
                    data = await ws.recv()
                    msg = json.loads(data)
                    
                    if msg.get("event") != "new_message":
                        continue
                    
                    m = msg["data"]
                    sender = m["from"]
                    content = m["content"]
                    to = m.get("to", "all")
                    
                    if sender == agent_name:
                        continue
                    
                    result = None
                    
                    # Mensagem do user
                    if sender == "user" and (to == "all" or to == agent_name):
                        result = parse_user_request(agent_name, content)
                    
                    # Mensagem de outro bot DIRECTAMENTE para mim
                    elif sender in ["claude", "codex"] and to == agent_name:
                        result = respond_to_bot(agent_name, sender, content)
                    
                    if not result:
                        continue
                    
                    response, reply_to = result
                    print(f"[{agent_name}] {sender}: {content[:30]}... -> {reply_to}: {response[:30]}...", file=sys.stderr)
                    
                    await asyncio.sleep(0.3)
                    
                    async with httpx.AsyncClient() as client:
                        await client.post(f"{api_url}/send", json={
                            "from": agent_name,
                            "to": reply_to,
                            "type": "chat",
                            "content": response
                        })
                        
                except Exception as e:
                    print(f"[{agent_name}] Erro: {e}", file=sys.stderr)
                    
    except websockets.exceptions.ConnectionClosed:
        pass

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="claude")
    parser.add_argument("--api", default="http://localhost:9999/api")
    args = parser.parse_args()
    
    while True:
        await run_bot(args.name, args.api)
        await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
