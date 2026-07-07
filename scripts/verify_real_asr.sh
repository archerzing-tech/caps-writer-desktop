#!/usr/bin/env bash
set +e
cd /Users/ericever/work/skill/caps-writer-desktop

echo '== A. kill stale (idempotent) =='
lsof -tiTCP:6016 -sTCP:LISTEN 2>/dev/null | xargs -r kill -9 2>/dev/null
pkill -9 -f capswriter-desktop 2>/dev/null
pkill -9 -f caps-writer-server 2>/dev/null
sleep 2
lsof -iTCP:6016 -sTCP:LISTEN 2>&1 || echo '6016 free'

echo
echo '== B. write probe script (no inline heredoc needed) =='
cat > scripts/_probe_audio.py <<'PYEOF'
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
PYEOF
ls -la scripts/_probe_audio.py

echo
echo '== C. launch binary directly from project tree =='
: > /tmp/caps-real.log
./src-tauri/target/release/caps-writer-desktop > /tmp/caps-real.log 2>&1 &
PID=$!
echo "Rust_PID=$PID"

echo
echo '== D. poll 6016 up to 60s =='
for i in $(seq 1 12); do
  sleep 5
  PYPID=$(lsof -tiTCP:6016 -sTCP:LISTEN 2>/dev/null | head -1)
  if [ -n "$PYPID" ]; then
    echo "t=$((i*5))s 6016_UP python_pid=$PYPID"
    break
  fi
  NOTDEAD=$(kill -0 $PID 2>/dev/null; echo $?)
  echo "t=$((i*5))s waiting rust_alive=$NOTDEAD"
done

echo
echo '== E. log lines =='
grep -E '\[Server\]|\[ASR\]|\[Mock\]|\[sidecar\]|\[launcher\]|engine|Failed|File doesn' /tmp/caps-real.log | head -30

echo
echo '== F. python holding model files? =='
PYPID=$(lsof -tiTCP:6016 -sTCP:LISTEN 2>/dev/null | head -1)
if [ -n "$PYPID" ]; then
  echo "-- .onnx/.bin held open --"
  lsof -p "$PYPID" 2>/dev/null | awk '$5=="REG" || $5=="REG;"' | grep -E '\.(onnx|bin|tiktoken)' | awk '{print $9}' | head -8
  echo "-- memory --"
  ps -p "$PYPID" -o pid,rss,command 2>&1 | head -2
fi

echo
echo '== G. run probe (real engine?) =='
python3 scripts/_probe_audio.py 2>&1 | head -25

echo
echo '== H. cleanup =='
pkill -9 -f capswriter-desktop 2>/dev/null
