#!/usr/bin/env python3
"""
Monitor que fica a ouvir mensagens e notifica quando há novas.
"""
import asyncio
import json
import websockets

async def monitor():
    uri = "ws://localhost:9999/ws/claude-monitor"
    print("A ligar ao servidor...")
    
    async with websockets.connect(uri) as ws:
        print("Ligado! A ouvir mensagens...")
        
        while True:
            try:
                data = await ws.recv()
                msg = json.loads(data)
                
                if msg.get("event") == "new_message":
                    m = msg["data"]
                    if m["from"] != "claude":  # Não mostrar as minhas próprias
                        print(f"\n>>> NOVA MENSAGEM de [{m['from']}]: {m['content']}")
                        print(">>> Responde com: curl -X POST http://localhost:9999/api/send -H 'Content-Type: application/json' -d @/tmp/reply.json")
                        
            except Exception as e:
                print(f"Erro: {e}")
                break

if __name__ == "__main__":
    asyncio.run(monitor())
