import asyncio, httpx, io, wave
import websockets

async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=100) as c:
        r = await c.post("/api/v1/voice/business-chat", json={"text":"hello"})
        assert r.status_code in (401, 403), "Unauthenticated voice chat was accepted"
        r = await c.post("/api/v1/auth/demo-login")
        print("demo",r.status_code)
        assert r.status_code == 200
        csrf = r.json().get("csrf_token") or c.cookies.get("csrf_token")
        c.headers["X-CSRF-Token"] = csrf
        r = await c.post("/api/v1/voice/business-chat",json={"text":"Mere godown mein kitna stock hai?"})
        print("chat",r.status_code,r.json())
        r = await c.post("/api/v1/voice/speak",json={"text":"नमस्ते। मेरे गोदाम में कितना स्टॉक है?"})
        print("speech",r.status_code,r.headers.get("content-type"),len(r.content))
        if r.status_code != 200: return
        with wave.open(io.BytesIO(r.content)) as w:
            rate=w.getframerate(); pcm=w.readframes(w.getnframes())
            print("sample rate",rate,"channels",w.getnchannels())
        ticket=(await c.post("/api/v1/ws-ticket")).json()["ticket"]
        async with websockets.connect(f"ws://127.0.0.1:8000/api/v1/live/transcribe?ticket={ticket}&sample_rate={rate}&diarize=false") as ws:
            for start in range(0,len(pcm),8192):
                await ws.send(pcm[start:start+8192])
                await asyncio.sleep(8192 / (2 * rate))
            await ws.send('{"action":"stop"}')
            while True:
                import json
                result=json.loads(await asyncio.wait_for(ws.recv(),90))
                print("transcription",result)
                if result.get("action") in ("stopped","error"): break
        assert result.get("confirmed"), "Synthetic Hindi audio was not transcribed"
        reply = await c.post("/api/v1/voice/business-chat",json={"text":result["confirmed"]})
        assert reply.status_code == 200, reply.status_code
        spoken = await c.post("/api/v1/voice/speak",json={"text":reply.json()["response"]})
        assert spoken.status_code == 200 and len(spoken.content) > 44
        print("Full voice -> AI -> voice PASS",len(spoken.content),"audio bytes")
asyncio.run(main())