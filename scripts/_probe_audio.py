import asyncio, json, base64, sys
try:
    import websockets, numpy as np
except ImportError as e:
    print('IMPORT_FAIL', e); sys.exit(0)
async def go():
    try:
        async with websockets.connect('ws://127.0.0.1:6016', open_timeout=5) as ws:
            sr = 16000
            tone = 0.3*np.sin(2*np.pi*440*np.linspace(0,0.3,int(sr*0.3),endpoint=False)).astype(np.float32)
            sil = np.zeros(int(sr*0.3), dtype=np.float32)
            wav = np.concatenate([tone, sil]).astype(np.float32)
            await ws.send(json.dumps({
                'type':'audio','task_id':'p1','is_final':True,'time_start':0,
                'sample_rate':sr,'format':'float32','channels':1,
                'samples':len(wav),'duration':len(wav)/sr,
                'audio':base64.b64encode(wav.tobytes()).decode(),
            }, ensure_ascii=False))
            print('SENT samples', len(wav))
            for i in range(5):
                try:
                    r = await asyncio.wait_for(ws.recv(), timeout=30)
                    d = json.loads(r)
                    print('RECV[%d]:' % i, json.dumps(d, ensure_ascii=False)[:400])
                    if 'text' in d or d.get('type')=='result':
                        break
                except asyncio.TimeoutError:
                    print('OUT[%d] TIMEOUT' % i); break
    except Exception as e:
        print('WS_FAIL', type(e).__name__, str(e)[:200])
asyncio.run(go())
