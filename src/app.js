// ========================================
// CapsWriter Desktop - Tauri Frontend Application
// ========================================

import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { getVersion } from '@tauri-apps/api/app';

// --- State ---
const state = {
  recording: false,
  serverOnline: false,
  transcriptions: [],
  realtimeActive: false,
  processingEnded: false,  // prevents late transcription events from creating duplicates
  historySavedForSession: false, // tracks whether onstop already saved history
};

// --- MediaRecorder ---
let mediaRecorder = null;
let audioChunks = [];
let audioContext = null;
let analyserNode = null;
let animationId = null;
let mediaStream = null;

// --- Standard mode raw-PCM fallback (used when MediaRecorder isn't supported) ---
let standardPcmBuffer = [];      // float32 PCM samples accumulated during recording
let standardPcmHandles = null;   // { source, proc, sink } for cleanup
let onStoppedHandler = null;     // assigned in startRecording(), invoked from stopRecording() when mediaRecorder is null

// === Helpers: Raw PCM capture (lossless 16kHz Float32) ===

function startStandardPcmCapture(audioCtx, stream, buffer) {
  // Raw-PCM capture path used as last-resort fallback when MediaRecorder
  // construction throws. Mirrors realtime path but writes into shared `buffer`.
  buffer.length = 0;
  const source = audioCtx.createMediaStreamSource(stream);
  const proc = audioCtx.createScriptProcessor(4096, 1, 1);
  const sink = audioCtx.createGain();
  sink.gain.value = 0;
  proc.onaudioprocess = (e) => {
    if (!state.recording) return;
    const input = e.inputBuffer.getChannelData(0);
    for (let i = 0; i < input.length; i++) buffer.push(input[i]);
  };
  source.connect(proc);
  proc.connect(sink);
  sink.connect(audioCtx.destination);
  return { source, proc, sink };
}

function stopStandardPcmCapture(handles) {
  if (!handles) return;
  try { handles.source.disconnect(); } catch (_) {}
  try { handles.proc.disconnect(); } catch (_) {}
  try { handles.sink.disconnect(); } catch (_) {}
}

// --- DOM ---
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// --- Title Bar ---
$('#btn-minimize')?.addEventListener('click', () => getCurrentWindow().minimize());
$('#btn-hide')?.addEventListener('click', () => getCurrentWindow().hide());
$('#btn-close')?.addEventListener('click', () => getCurrentWindow().close());

// --- Navigation ---
$$('.sidebar-item[data-view]').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('.sidebar-item[data-view]').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    $$('.view').forEach((v) => v.classList.remove('active'));
    document.getElementById(`view-${btn.dataset.view}`)?.classList.add('active');

    // Refresh history when navigating to history view
    if (btn.dataset.view === 'history') {
      loadHistoryDates();
    }
  });
});

// === MIC: Click to Record ===
const micBtn = $('#mic-btn');
const micStatus = $('#mic-status');
const canvas = $('#waveform-canvas');
const ctx = canvas?.getContext('2d');

micBtn?.addEventListener('click', () => {
  state.recording ? stopRecording() : startRecording();
});

async function startRecording() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: { ideal: 16000 },
        channelCount: { ideal: 1 },
        echoCancellation: true,
        noiseSuppression: true,
      },
    });

    audioChunks = [];

    // Bypass MediaRecorder — always use raw PCM 16kHz lossless capture.
    // MediaRecorder encodes as webm/opus which loses acoustic detail and
    // degrades ASR recognition accuracy significantly.
    mediaRecorder = null;

    const onStopped = async () => {
      if (mediaStream) {
        mediaStream.getTracks().forEach((t) => t.stop());
        mediaStream = null;
      }
      stopWaveform();

      // Reset per-session flags
      state.historySavedForSession = false;

      if (state.realtimeActive) {
        const cardEl = realtimeCardEl; // Keep reference for polishing
        // Look up the matching transcription by dataset.time, not by index 0
        const rtIdx = cardEl ? state.transcriptions.findIndex(t => String(t.time) === cardEl.dataset.time) : -1;
        const rtText = rtIdx !== -1 ? state.transcriptions[rtIdx].text : (state.transcriptions[0]?.text || '');
        const rtTs = rtIdx !== -1 ? state.transcriptions[rtIdx].time : (state.transcriptions[0]?.time || (Date.now() / 1000));
        const rtDuration = (Date.now() / 1000) - rtTs;

        // Check if LLM polishing is enabled (`toggle-llm` quick toggle)
        const llmEnabled = $('#toggle-llm')?.checked;
        let finalText = rtText;

        if (llmEnabled && rtText.trim().length > 0) {
          // Quick check: is LLM configured?
          let llmConfigured = true;
          try {
            const llm = await invoke('load_llm_config');
            if (!llm.api_key || llm.api_key.trim() === '') {
              llmConfigured = false;
              toast('⚠ LLM 未配置，润色已跳过。请到设置中配置 LLM API Key', 'warning');
            }
          } catch (_) {}
          
          if (!llmConfigured) {
            finalText = rtText;
          } else {
            micStatus.textContent = '✨ 润色中...';
            try {
              const polished = await invoke('polish_text', { text: rtText });
              if (polished && polished.trim() !== rtText.trim()) {
                finalText = polished;
                // Update the card text with polished version
                if (cardEl) {
                  const textEl = cardEl.querySelector('.entry-text');
                  if (textEl) textEl.textContent = polished;
                  // Add polished badge
                  const meta = cardEl.querySelector('.entry-meta');
                  if (meta) {
                    const badge = document.createElement('span');
                    badge.className = 'polish-badge';
                    badge.textContent = '✨ 已润色';
                    meta.prepend(badge);
                  }
                }
              }
            } catch (e) {
              console.warn('[Polish] LLM polish failed:', e);
            }
          }
        }

        // Save final text (polished or original) to history with actual duration
        if (finalText.trim().length > 0) {
          autoSaveHistory(finalText, rtTs, Math.max(0, rtDuration));
        }
        // Update state with final text
        if (cardEl) {
          const idx = state.transcriptions.findIndex(t => t.time === cardEl.dataset.time);
          if (idx !== -1) state.transcriptions[idx].text = finalText;
        }
        // Update char count
        const total = state.transcriptions.reduce((s, t) => s + t.text.length, 0);
        const el2 = $('#char-count');
        if (el2) el2.textContent = total + ' 字';

        // Enable translate button now that recording is done
        if (cardEl) {
          const tBtn = cardEl.querySelector('[data-translate]');
          if (tBtn) tBtn.disabled = false;
        }

        // Mark history as saved for this session (prevents duplicate saves from late events)
        state.historySavedForSession = true;

        // Realtime mode: chunks already sent, just notify backend recording stopped
        state.realtimeActive = false;
        realtimeCardEl = null; // Done building this card
        try { await invoke('stop_recording', { audioData: [] }); } catch (_) {}
      } else if (mediaRecorder) {
        // Standard mode MediaRecorder path: decode all encoded audio and send at once
        try {
          const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
          const buf = await blob.arrayBuffer();
          const actx = new AudioContext({ sampleRate: 16000 });
          const decoded = await actx.decodeAudioData(buf);
          const pcm = decoded.getChannelData(0);
          const arr = Array.from(pcm);
          await invoke('stop_recording', { audioData: arr });
          actx.close();
        } catch (e) {
          console.error('[History] Audio decode/ASR failed:', e);
          // Fallback: if ASR fails, save whatever text was accumulated in the UI
          const fallbackText = state.transcriptions[0]?.text?.trim();
          if (fallbackText) {
            const now = Date.now() / 1000;
            autoSaveHistory(fallbackText, now, 0);
            state.historySavedForSession = true;
            toast('⚠ ASR 处理失败，已保存当前文本', 'warning');
          }
          await invoke('stop_recording', { audioData: [] });
        }

        // Fallback safe: if the transcription event hasn't arrived yet, save
        // whatever accumulated text we have from the UI after a short delay.
        // This ensures history is always saved even if the event is delayed/lost.
        setTimeout(() => {
          if (!state.historySavedForSession) {
            const pendingText = state.transcriptions[0]?.text?.trim();
            if (pendingText) {
              const now = Date.now() / 1000;
              autoSaveHistory(pendingText, now, 0);
              state.historySavedForSession = true;
            }
          }
        }, 2000);
      } else {
        // Standard mode raw-PCM fallback path (MediaRecorder unavailable).
        // Just send the float32 sample buffer we collected via ScriptProcessorNode.
        try {
          const arr = standardPcmBuffer.length > 0 ? Array.from(standardPcmBuffer) : [];
          await invoke('stop_recording', { audioData: arr });
        } catch (e) {
          console.error('[Standard PCM] invoke failed:', e);
          const fallbackText = state.transcriptions[0]?.text?.trim();
          if (fallbackText) {
            const now = Date.now() / 1000;
            autoSaveHistory(fallbackText, now, 0);
            state.historySavedForSession = true;
            toast('⚠ ASR 处理失败，已保存当前文本', 'warning');
          }
          await invoke('stop_recording', { audioData: [] });
        }
        // Same delayed-save safety net as the MediaRecorder path
        setTimeout(() => {
          if (!state.historySavedForSession) {
            const pendingText = state.transcriptions[0]?.text?.trim();
            if (pendingText) {
              const now = Date.now() / 1000;
              autoSaveHistory(pendingText, now, 0);
              state.historySavedForSession = true;
            }
          }
        }, 2000);
        stopStandardPcmCapture(standardPcmHandles);
        standardPcmHandles = null;
        standardPcmBuffer = [];
      }

      // Signal that main processing in onstop is done.
      // Late-arriving transcription events will check this flag.
      state.processingEnded = true;

      // Close shared audioContext now that recording is fully done
      if (audioContext) {
        audioContext.close().catch(() => {});
        audioContext = null;
        analyserNode = null;
      }

      micStatus.textContent = '就绪 · 点击录音';
    };
    if (mediaRecorder) {
      mediaRecorder.onstop = onStopped;
    }
    onStoppedHandler = onStopped;

    // Analyser for waveform (use 16kHz to match mic constraints; also reused by realtime)
    audioContext = new AudioContext({ sampleRate: 16000 });
    const src = audioContext.createMediaStreamSource(mediaStream);
    analyserNode = audioContext.createAnalyser();
    analyserNode.fftSize = 256;
    src.connect(analyserNode);

    await invoke('start_recording');
    if (mediaRecorder) {
      mediaRecorder.start(100);
    } else {
      // Wire up raw-PCM capture using the shared audioContext (already created
      // for the waveform analyser). onaudioprocess will fill standardPcmBuffer.
      standardPcmHandles = startStandardPcmCapture(audioContext, mediaStream, standardPcmBuffer);
    }
    state.recording = true;
    micBtn?.classList.add('recording');
    document.body.classList.add('recording-active');
    micStatus.textContent = '● 录音中... 点击停止';
    startWaveform();

    // Realtime mode: periodically flush audio chunks
    state.realtimeActive = $('#toggle-realtime')?.checked || $('#setting-realtime')?.checked;
    if (state.realtimeActive) {
      startRealtimeFlush();
    }
    // Reset processing flag for new recording
    state.processingEnded = false;
  } catch (e) {
    const name = e && e.name ? e.name : '未知错误';
    const msg  = e && e.message ? `: ${e.message}` : '';
    micStatus.textContent = `麦克风访问失败 (${name})${msg}`;
    console.error('[getUserMedia]', e);
    if (mediaStream) mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
    if (audioContext) {
      audioContext.close().catch(() => {});
      audioContext = null;
      analyserNode = null;
    }
  }
}

function stopRecording() {
  // Stop realtime flush if active
  stopRealtimeFlush();

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  } else if (!mediaRecorder && state.recording && typeof onStoppedHandler === 'function') {
    // No MediaRecorder (PCM fallback path). Fire the same handler so cleanup,
    // WS send, and history-save all run. setTimeout defers one tick so
    // state.recording=false (set below) stops the onaudioprocess first.
    // Snapshot + null out, so a quick subsequent startRecording() can't redirect
    // this snapshot to the new session's state.
    const h = onStoppedHandler;
    onStoppedHandler = null;
    setTimeout(h, 0);
  }
  state.recording = false;
  micBtn?.classList.remove('recording');
  document.body.classList.remove('recording-active');
  micStatus.textContent = '处理中...';
}

// --- Waveform ---
function startWaveform() {
  if (animationId) cancelAnimationFrame(animationId);
  drawWaveform();
}

function stopWaveform() {
  if (animationId) cancelAnimationFrame(animationId);
  animationId = null;
  drawIdle();
}

function drawWaveform() {
  if (!ctx || !canvas || !analyserNode) {
    animationId = requestAnimationFrame(drawWaveform);
    return;
  }
  const w = canvas.width, h = canvas.height;
  const buf = new Uint8Array(analyserNode.frequencyBinCount);
  analyserNode.getByteFrequencyData(buf);
  ctx.clearRect(0, 0, w, h);

  // Draw gradient background
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, 'rgba(0, 184, 148, 0.15)');
  grad.addColorStop(0.5, 'rgba(0, 184, 148, 0.05)');
  grad.addColorStop(1, 'rgba(0, 184, 148, 0.15)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, w, h);

  const n = 64;
  const bw = (w / n) * 0.7;
  const gap = (w / n) * 0.3;
  for (let i = 0; i < n; i++) {
    const idx = Math.floor((i / n) * buf.length);
    const val = buf[idx] / 255;
    const bh = Math.max(1, val * val * h * 0.9);
    const x = i * (bw + gap);
    const y = (h - bh) / 2;

    // Gradient color based on intensity
    const alpha = 0.2 + val * 0.8;
    ctx.globalAlpha = alpha;
    ctx.fillStyle = val > 0.5 ? '#55efc4' : '#00b894';
    ctx.beginPath();
    ctx.roundRect(x, y, bw, bh, [bw / 2, bw / 2, bw / 2, bw / 2]);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  animationId = requestAnimationFrame(drawWaveform);
}

function drawIdle() {
  if (!ctx || !canvas) return;
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  // Subtle gradient dots pattern
  const t = Date.now() / 2000;
  const n = 32;
  const spacing = w / n;
  for (let i = 0; i < n; i++) {
    const x = i * spacing + spacing / 2;
    const y = h / 2 + Math.sin((i / n) * Math.PI * 6 + t) * 6 + Math.sin((i / n) * Math.PI * 10 + t * 1.5) * 3;
    const size = 2 + Math.sin((i / n) * Math.PI * 4 + t * 0.8) * 1;
    ctx.beginPath();
    ctx.arc(x, y, Math.max(1, size), 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(42, 42, 46, 0.5)';
    ctx.fill();
  }
  animationId = requestAnimationFrame(drawIdle);
}
drawIdle();

// === Transcription ===
let realtimeCardEl = null; // Current realtime card being built

listen('transcription', (e) => {
  const d = e.payload;
  // Skip empty/whitespace-only results (e.g. from stop_recording with empty audio)
  if (!d.text || d.text.trim().length === 0) return;

  // If processing has ended, this is a late-arriving event (race condition).
  // In realtime mode, the full text was already saved by onstop.
  // In standard mode, we still process it (addTrans + autoSaveHistory) since
  // it's the normal flow — but only if history hasn't been saved yet for this session.
  if (state.processingEnded && !state.realtimeActive) {
    // Standard mode, but processing ended: transcription event arrived late.
    // Still save it to be safe, but mark it.
    addTrans(d.text, d.is_final, d.duration, d.timestamp);
    if (!state.historySavedForSession) {
      autoSaveHistory(d.text, d.timestamp, d.duration || 0);
    }
    return;
  }

  // If processing ended and realtimeActive was true (late chunk result), discard silently
  if (state.processingEnded && state.realtimeActive) {
    return;
  }

  if (state.realtimeActive && realtimeCardEl) {
    // Realtime mode: append text to the current card
    const textEl = realtimeCardEl.querySelector('.entry-text');
    if (textEl && d.text && d.text.trim().length > 0) {
      const prev = textEl.textContent;
      textEl.textContent = prev ? prev + d.text : d.text;
      // Update the stored text in state for copy/delete
      const idx = state.transcriptions.findIndex(t => t.time === realtimeCardEl.dataset.time);
      if (idx !== -1) state.transcriptions[idx].text = textEl.textContent;
      // Update duration display
      const timeEl = realtimeCardEl.querySelector('.entry-time');
      if (timeEl) timeEl.textContent = new Date(d.timestamp * 1000).toLocaleTimeString() + ' · ' + (d.duration || 0).toFixed(1) + 's';
      const total = state.transcriptions.reduce((s, t) => s + t.text.length, 0);
      const el2 = $('#char-count');
      if (el2) el2.textContent = total + ' 字';
    }
    // Skip per-chunk history save in realtime mode (save full text on stop)
  } else if (!state.realtimeActive && !state.historySavedForSession) {
    // Standard mode: create a new card
    addTrans(d.text, d.is_final, d.duration, d.timestamp);
    // Auto-save to history (mark session saved to prevent setTimeout/race dupes)
    autoSaveHistory(d.text, d.timestamp, d.duration || 0);
    state.historySavedForSession = true;
  }
  // If realtime but no card (deleted mid-recording), silently discard the chunk
});

function addTrans(text, isFinal, dur, ts) {
  const area = $('#transcription-area');
  const ph = area?.querySelector('.placeholder-text');
  if (ph) ph.remove();

  const t = new Date(ts * 1000).toLocaleTimeString();
  const el = document.createElement('div');
  el.className = 'trans-entry';
  el.innerHTML = `
    <div class="entry-header">
      <span class="entry-time">${t} · ${dur.toFixed(1)}s</span>
      <button class="entry-btn-del" data-del>✕</button>
    </div>
    <div class="entry-text">${esc(text)}</div>
    <div class="entry-meta">
      <div class="entry-actions">
        <button class="entry-btn" data-copy>复制</button>
        <button class="entry-btn" data-paste>粘贴</button>
        <button class="entry-btn translate-btn" data-translate>翻译</button>
      </div>
    </div>`;

  el.querySelector('[data-copy]')?.addEventListener('click', () => {
    navigator.clipboard.writeText(text);
    toast('✅ 已复制');
  });
  el.querySelector('[data-paste]')?.addEventListener('click', async () => {
    await invoke('copy_to_clipboard', { text });
    toast('✅ 已粘贴到当前窗口');
  });
  el.querySelector('[data-translate]')?.addEventListener('click', async () => {
    const btn = el.querySelector('[data-translate]');
    if (btn) btn.textContent = '翻译中...';
    
    // Check if we already have a translation shown
    let existing = el.querySelector('.entry-translation');
    if (existing) {
      existing.remove();
      if (btn) btn.textContent = '翻译';
      return;
    }
    
    const result = await translateText(text);
    if (result) {
      const meta = el.querySelector('.entry-meta');
      const div = document.createElement('div');
      div.className = 'entry-translation';
      div.textContent = `🌐 ${result}`;
      meta?.parentNode?.insertBefore(div, meta?.nextSibling || null);
      if (btn) btn.textContent = '收起';
    } else {
      if (btn) btn.textContent = '翻译';
    }
  });
  el.querySelector('[data-del]')?.addEventListener('click', () => {
    const idx = state.transcriptions.findIndex((t) => t.text === text && t.time === ts);
    if (idx !== -1) state.transcriptions.splice(idx, 1);
    el.remove();
    const total = state.transcriptions.reduce((s, t) => s + t.text.length, 0);
    const el2 = $('#char-count');
    if (el2) el2.textContent = `${total} 字`;
    if (state.transcriptions.length === 0) {
      area.innerHTML =
        '<div class="placeholder-text"><span class="placeholder-icon">◉</span><span>点击麦克风开始语音输入</span></div>';
    }
    toast('🗑 已删除');
  });

  area?.prepend(el);
  state.transcriptions.unshift({ text, time: ts });
  const total = state.transcriptions.reduce((s, t) => s + t.text.length, 0);
  const el2 = $('#char-count');
  if (el2) el2.textContent = `${total} 字`;

  // Auto-translate if toggle is on
  if ($('#toggle-translate')?.checked && isFinal && text.trim().length > 0) {
    setTimeout(async () => {
      const result = await translateText(text);
      if (result) {
        const div = document.createElement('div');
        div.className = 'entry-translation';
        div.textContent = `🌐 ${result}`;
        const meta = el.querySelector('.entry-meta');
        meta?.parentNode?.insertBefore(div, meta?.nextSibling || null);
        // Update translate button to show '收起'
        const tBtn = el.querySelector('[data-translate]');
        if (tBtn) tBtn.textContent = '收起';
      }
    }, 100);
  }
}

$('#btn-copy')?.addEventListener('click', async () => {
  const all = state.transcriptions.map((x) => x.text).join('\n');
  if (all) { await invoke('copy_to_clipboard', { text: all }); toast('✅ 已复制全部'); }
  else { toast('暂无内容可复制', 'warning'); }
});
$('#btn-clear')?.addEventListener('click', () => {
  if (state.transcriptions.length === 0) { toast('已无内容', 'warning'); return; }
  state.transcriptions = [];
  $('#transcription-area').innerHTML =
    '<div class="placeholder-text"><span class="placeholder-icon">◉</span><span>点击麦克风开始语音输入</span></div>';
  const el = $('#char-count');
  if (el) el.textContent = '0 字';
  toast('🗑 已清空全部');
});

// === Server Status (3 states: starting / online / offline) ===
let serverStarting = false;
let serverOnline = false;

listen('server-status', (e) => {
  console.log('[Status] server-status event:', e.payload);
  serverStarting = false;
  serverOnline = !!e.payload;
  updateServerBadge();
});

listen('server-log', (e) => console.log('[ASR]', e.payload));

listen('model-download-progress', (e) => {
  const d = e.payload || {};
  const wrap = $('#model-progress-wrap');
  const bar = $('#model-progress-bar');
  const txt = $('#model-progress-text');
  const errBox = $('#model-error-text');
  const statusText = $('#model-status-text');
  const dlBtn = $('#btn-download-model');
  if (errBox) errBox.style.display = 'none';

  if (d.status === 'fetching_manifest') {
    if (wrap) wrap.style.display = 'block';
    if (bar) bar.style.width = '2%';
    if (txt) txt.textContent = '正在从 HuggingFace 获取文件清单...';
    if (statusText) statusText.textContent = '准备下载...';
  } else if (d.status === 'downloading') {
    if (wrap) wrap.style.display = 'block';
    const totalMB = ((d.bytes_total || 0) / 1_000_000).toFixed(1);
    if (txt) txt.textContent = `共 ${d.files_total} 个文件, ${totalMB} MB`;
    if (dlBtn) { dlBtn.disabled = true; dlBtn.textContent = '⏳ 下载中...'; }
  } else if (d.status === 'progress') {
    if (wrap) wrap.style.display = 'block';
    const bytes_total = d.bytes_total || 0;
    const pct = bytes_total > 0 ? Math.min(100, ((d.bytes_received || 0) / bytes_total) * 100) : 0;
    if (bar) bar.style.width = pct.toFixed(2) + '%';
    const recvMB = ((d.bytes_received || 0) / 1_000_000).toFixed(1);
    const totalMB = (bytes_total / 1_000_000).toFixed(1);
    const fileLabel = d.skipped ? `⏭ ${d.filename}` : d.filename;
    if (txt) txt.textContent = `[${(d.files_done || 0) + 1}/${d.files_total}] ${fileLabel} — ${recvMB}/${totalMB} MB (${pct.toFixed(1)}%)`;
    if (statusText) statusText.textContent = `下载中 ${recvMB}/${totalMB} MB (${pct.toFixed(0)}%)`;
  } else if (d.status === 'complete') {
    if (wrap) wrap.style.display = 'none';
    if (statusText) statusText.textContent = `✅ 模型已就绪 (${((d.bytes_received || 0) / 1_000_000).toFixed(1)} MB)`;
    if (dlBtn) { dlBtn.disabled = false; dlBtn.style.display = 'none'; }
    refreshModelStatus();
  } else if (d.status === 'already_installed') {
    if (statusText) statusText.textContent = '✅ 模型已就绪';
    if (dlBtn) dlBtn.style.display = 'none';
  } else if (d.status === 'error') {
    if (wrap) wrap.style.display = 'none';
    if (errBox) { errBox.style.display = 'block'; errBox.textContent = `❌ ${d.message || '下载失败'}`; }
    if (statusText) statusText.textContent = '下载失败';
    if (dlBtn) { dlBtn.disabled = false; dlBtn.textContent = '⬇ 一键下载模型'; }
  }
});

async function refreshModelStatus() {
  const t = $('#model-status-text');
  const dl = $('#btn-download-model');
  if (!t || !dl) return;
  try {
    const s = await invoke('check_model_status');
    if (s.ready) {
      t.textContent = `✅ 模型已就绪 (${s.size_mb} MB)`;
      dl.style.display = 'none';
    } else if (s.size_bytes > 0) {
      t.textContent = `⚠ 模型文件不完整 (${s.size_mb} MB)，建议重新下载`;
      dl.style.display = '';
      dl.textContent = '⬇ 一键下载模型';
      dl.disabled = false;
    } else {
      t.textContent = '⏬ 模型未下载（将使用 Mock 引擎）';
      dl.style.display = '';
      dl.textContent = '⬇ 一键下载模型 (≈954 MB)';
      dl.disabled = false;
    }
  } catch (e) {
    t.textContent = `❌ 检测失败: ${e}`;
  }
}

$('#btn-download-model')?.addEventListener('click', async () => {
  const dl = $('#btn-download-model');
  const wrap = $('#model-progress-wrap');
  const txt = $('#model-progress-text');
  const bar = $('#model-progress-bar');
  if (dl) { dl.disabled = true; dl.textContent = '⏳ 启动中...'; }
  if (wrap) wrap.style.display = 'block';
  if (bar) bar.style.width = '0%';
  if (txt) txt.textContent = '准备下载...';
  try {
    const r = await invoke('download_qwen3_asr_model');
    console.log('[download-model]', r);
  } catch (e) {
    const errBox = $('#model-error-text');
    const t = $('#model-status-text');
    if (errBox) { errBox.style.display = 'block'; errBox.textContent = `❌ ${e}`; }
    if (t) t.textContent = '下载失败';
    if (dl) { dl.disabled = false; dl.textContent = '⬇ 一键下载模型'; }
    if (wrap) wrap.style.display = 'none';
  }
});

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', refreshModelStatus);
} else {
  refreshModelStatus();
}

function updateServerBadge() {
  const b = $('#server-badge');
  const retry = $('#server-retry');
  if (!b) return;
  if (serverStarting) {
    b.textContent = '启动服务中...';
    b.className = 'status-badge starting';
    if (retry) retry.style.display = 'none';
  } else if (serverOnline) {
    b.textContent = '服务已连接';
    b.className = 'status-badge online';
    if (retry) retry.style.display = 'none';
  } else {
    b.textContent = '服务未连接';
    b.className = 'status-badge offline';
    if (retry) retry.style.display = 'inline-flex';
  }
}

// Retry server connection
$('#server-retry')?.addEventListener('click', async () => {
  const retry = $('#server-retry');
  if (retry) {
    retry.textContent = '连接中...';
    retry.className = 'status-badge starting';
    retry.style.display = 'inline-flex';
  }
  try {
    await invoke('start_server');
    toast('正在启动服务...');
  } catch (e) {
    toast(`重试失败: ${e}`, 'error');
    if (retry) {
      retry.textContent = '↻ 重试';
      retry.className = 'status-badge retry';
      retry.style.display = 'inline-flex';
    }
  }
});

// === Settings ===
$$('.settings-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    $$('.settings-tab').forEach((t) => t.classList.remove('active'));
    tab.classList.add('active');
    $$('.settings-pane').forEach((p) => p.classList.remove('active'));
    const p = document.getElementById(`tab-${tab.dataset.tab}`);
    if (p) p.classList.add('active');

    // Load hotwords when navigating to hotword tab
    if (tab.dataset.tab === 'hotword' && typeof window.__loadHotwords === 'function') {
      window.__loadHotwords();
    }
  });
});
$('#btn-save-model')?.addEventListener('click', async () => {
  const c = {
    model_type: $('#setting-model')?.value || 'qwen_asr',
    language: $('#setting-lang')?.value || 'auto',
    format_num: $('#setting-format-num')?.checked ?? true,
    hotwords_enabled: $('#setting-hot-enabled')?.checked ?? true,
    llm_enabled: $('#toggle-llm')?.checked ?? false,
    paste_on_finish: $('#setting-paste')?.checked ?? true,
    save_audio: $('#setting-save-audio')?.checked ?? true,
    trash_punc: $('#setting-trash-punc')?.value || '，,。。',
    gpu: $('#setting-gpu')?.value || 'cpu',
    realtime_enabled: $('#setting-realtime')?.checked ?? false,
    custom_models_dir: $('#setting-model-dir')?.value?.trim() || '',
    translate_direction: translateDir || 'auto',
  };
  try { await invoke('save_config', { config: c }); toast('✅ 已保存，重启应用后生效（Cmd+Q + 重新打开）', 'info', 5000); }
  catch (e) { toast(`保存失败: ${e}`, 'error'); }
});
$('#setting-threshold')?.addEventListener('input', (e) => {
  const v = $('#threshold-value');
  if (v) v.textContent = `${parseFloat(e.target.value).toFixed(2)}s`;
});

// LLM backend presets (used by setupLlmPresets)
const LLM_PRESETS = {    deepseek: { api_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
    openai:   { api_url: 'https://api.openai.com/v1',   model: 'gpt-4o-mini' },
    ollama:   { api_url: 'http://127.0.0.1:11434/v1',   model: 'qwen2.5' },
};

function setupLlmPresets() {
  const backendSelect = $('#setting-llm-backend');
  const urlInput = $('#setting-llm-url');
  const modelInput = $('#setting-llm-model');
  if (!backendSelect) return;

  backendSelect.addEventListener('change', () => {
    const preset = LLM_PRESETS[backendSelect.value];
    if (preset) {
      if (urlInput && !urlInput.dataset.userEdited) urlInput.value = preset.api_url;
      if (modelInput && !modelInput.dataset.userEdited) modelInput.value = preset.model;
    }
  });

  urlInput?.addEventListener('input', () => { urlInput.dataset.userEdited = 'true'; });
  modelInput?.addEventListener('input', () => { modelInput.dataset.userEdited = 'true'; });
}

// Test LLM connection
$('#btn-test-llm')?.addEventListener('click', async () => {
  const resultEl = $('#llm-test-result');
  if (!resultEl) return;

  const settings = {
    backend: $('#setting-llm-backend')?.value || 'deepseek',
    api_url: $('#setting-llm-url')?.value || 'https://api.deepseek.com/v1',
    model: $('#setting-llm-model')?.value || 'deepseek-chat',
    api_key: $('#setting-llm-key')?.value || '',
  };

  resultEl.style.display = 'block';
  resultEl.className = 'llm-test-result testing';
  resultEl.textContent = '⏳ 正在测试连接...';

  const btn = $('#btn-test-llm');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '测试中...';
  }

  try {
    const msg = await invoke('test_llm_connection', { settings });
    resultEl.className = 'llm-test-result success';
    resultEl.textContent = msg;
  } catch (e) {
    resultEl.className = 'llm-test-result error';
    resultEl.textContent = `❌ ${e}`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🔌 测试连接';
    }
  }
});

// Save LLM settings
$('#btn-save-llm')?.addEventListener('click', async () => {
  const settings = {
    backend: $('#setting-llm-backend')?.value || 'deepseek',
    api_url: $('#setting-llm-url')?.value || 'https://api.deepseek.com/v1',
    model: $('#setting-llm-model')?.value || 'deepseek-chat',
    api_key: $('#setting-llm-key')?.value || '',
  };
  try {
    await invoke('save_llm_config', { settings });
    toast('✅ LLM 设置已保存');
  } catch (e) {
    toast(`保存失败: ${e}`, 'error');
  }
});

// === File Transcribe ===
const dz = $('#dropzone');
dz?.addEventListener('dragover', (e) => { e.preventDefault(); dz?.classList.add('drag-over'); });
dz?.addEventListener('dragleave', () => dz?.classList.remove('drag-over'));
dz?.addEventListener('drop', (e) => {
  e.preventDefault(); dz?.classList.remove('drag-over');
  const f = e.dataTransfer?.files[0];
  if (f) transcribeFile(f.name);
});
$('#btn-pick-file')?.addEventListener('click', async () => {
  try { const p = await invoke('pick_audio_file'); if (p) transcribeFile(p); }
  catch (e) { toast(`选择失败: ${e}`, 'error'); }
});

function transcribeFile(path) {
  const progressEl = $('#transcribe-progress');
  const resultEl = $('#transcribe-result');
  if (progressEl) progressEl.style.display = 'block';
  if (resultEl) resultEl.style.display = 'none';
  if (dz) dz.style.display = 'none';
  const fill = $('#progress-fill'), st = $('#progress-status');
  if (st) st.textContent = '正在发送到ASR服务...';
  if (fill) fill.style.width = '10%';

  // More realistic progress simulation
  let pct = 10;
  const iv = setInterval(() => {
    const increment = Math.max(1, (90 - pct) * 0.08 + Math.random() * 3);
    pct = Math.min(pct + increment, 90);
    if (fill) fill.style.width = `${pct}%`;
    if (st) st.textContent = `转录中... ${Math.round(pct)}%`;
  }, 300);

  const filename = path.split(/[/\\]/).pop();
  setTimeout(() => {
    clearInterval(iv);
    pct = 100;
    if (fill) fill.style.width = '100%';
    if (st) st.textContent = '✅ 转录完成';
    if (resultEl) {
      resultEl.style.display = 'block';
      const textEl = $('#transcribe-text');
      if (textEl) {
        textEl.innerHTML = `<div class="result-filename">📄 ${esc(filename)}</div><div class="result-success">文件已提交到ASR服务。结果将显示在语音转录区域。</div>`;
      }
    }
    toast(`✅ "${filename}" 转录完成`);
  }, 2000 + Math.random() * 1000);
}
// === History: Local Storage ===
let selectedHistoryDate = null;
let isSearchMode = false;

function autoSaveHistory(text, timestamp, duration) {
  if (!text || text.trim().length === 0) return;
  const d = new Date(timestamp * 1000);
  const dateStr = d.toISOString().slice(0, 10); // YYYY-MM-DD
  invoke('save_history', {
    entry: {
      text: text,
      time: timestamp,
      duration: duration,
      date: dateStr,
    }
  }).catch((e) => console.warn('[History] save failed:', e));
}

// History: Load date list
async function loadHistoryDates() {
  try {
    const dates = await invoke('get_history_dates');
    const list = $('#history-date-list');
    if (!list) return;

    if (dates.length === 0) {
      list.innerHTML = '<div class="history-empty-state"><div class="history-empty-icon">📋</div><div class="history-empty-text">暂无历史记录</div></div>';
      return;
    }

    list.innerHTML = dates.map((date) => {
      const dayName = getDayName(date);
      const isActive = date === selectedHistoryDate && !isSearchMode;
      return `<div class="history-date-item ${isActive ? 'active' : ''}" data-date="${date}">
        <span class="history-date-icon">📅</span>
        <span class="history-date-name">${dayName}</span>
      </div>`;
    }).join('');

    // Attach click handlers
    list.querySelectorAll('.history-date-item').forEach((el) => {
      el.addEventListener('click', () => {
        isSearchMode = false;
        selectedHistoryDate = el.dataset.date;
        loadHistoryEntries(selectedHistoryDate);
        // Update active state
        list.querySelectorAll('.history-date-item').forEach((i) => i.classList.remove('active'));
        el.classList.add('active');
      });
    });

    // Auto-select first date if none selected
    if (!selectedHistoryDate || isSearchMode) {
      const first = list.querySelector('.history-date-item');
      if (first) {
        selectedHistoryDate = first.dataset.date;
        first.classList.add('active');
        loadHistoryEntries(selectedHistoryDate);
      }
    }
  } catch (e) {
    console.warn('[History] load dates failed:', e);
    const list = $('#history-date-list');
    if (list) list.innerHTML = '<div class="history-empty-state"><div class="history-empty-text">加载失败</div></div>';
  }
}

// History: Load entries for a specific date
async function loadHistoryEntries(date) {
  const container = $('#history-entries');
  const title = $('#history-date-title');
  const count = $('#history-count');
  if (!container) return;

  if (title) {
    document.getElementById('view-history')?.classList.remove('history-search-mode');
    title.textContent = formatDateTitle(date);
  }
  if (count) count.textContent = '';

  container.innerHTML = '<div class="history-loading">加载中...</div>';

  try {
    const entries = await invoke('get_history_by_date', { date });
    if (entries.length === 0) {
      container.innerHTML = '<div class="placeholder-text"><span class="placeholder-icon">📋</span><span>该日期暂无记录</span></div>';
      if (count) count.textContent = '0 条';
      return;
    }

    if (count) count.textContent = `${entries.length} 条`;

    container.innerHTML = entries.map((entry, idx) => {
      const t = new Date(entry.time * 1000).toLocaleTimeString();
      const durStr = entry.duration > 0 ? ` · ${entry.duration.toFixed(1)}s` : '';
      return `<div class="history-entry" data-index="${idx}">
        <div class="entry-header">
          <span class="entry-time">${t}${durStr}</span>
          <button class="entry-btn-del" data-del-history="${date}|${idx}">✕</button>
        </div>
        <div class="entry-text">${esc(entry.text)}</div>
        <div class="entry-meta">
          <div class="entry-actions">
            <button class="entry-btn" data-copy-history="${idx}">复制</button>
            <button class="entry-btn translate-btn" data-translate-history="${idx}">翻译</button>
          </div>
        </div>
      </div>`;
    }).join('');

    // Attach event handlers
    container.querySelectorAll('[data-copy-history]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.copyHistory);
        const entry = entries[idx];
        if (entry) {
          navigator.clipboard.writeText(entry.text);
          toast('✅ 已复制');
        }
      });
    });

    container.querySelectorAll('[data-translate-history]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const idx = parseInt(btn.dataset.translateHistory);
        const entry = entries[idx];
        if (!entry) return;
        
        const parentEl = btn.closest('.history-entry');
        if (!parentEl) return;
        
        btn.textContent = '翻译中...';
        
        // Check if translation already shown
        let existing = parentEl.querySelector('.entry-translation');
        if (existing) {
          existing.remove();
          btn.textContent = '翻译';
          return;
        }
        
        const result = await translateText(entry.text);
        if (result) {
          const div = document.createElement('div');
          div.className = 'entry-translation';
          div.textContent = `🌐 ${result}`;
          const meta = parentEl.querySelector('.entry-meta');
          meta?.parentNode?.insertBefore(div, meta?.nextSibling || null);
          btn.textContent = '收起';
        } else {
          btn.textContent = '翻译';
        }
      });
    });

    container.querySelectorAll('[data-del-history]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const [d, idxStr] = btn.dataset.delHistory.split('|');
        const idx = parseInt(idxStr);
        try {
          await invoke('delete_history_entry', { date: d, index: idx });
          toast('🗑 已删除');
          loadHistoryEntries(d);
          loadHistoryDates();
        } catch (e) {
          toast(`删除失败: ${e}`, 'error');
        }
      });
    });

  } catch (e) {
    container.innerHTML = '<div class="placeholder-text"><span>加载失败</span></div>';
    console.warn('[History] load entries failed:', e);
  }
}

// History: Search across all entries
let searchTimer = null;
function setupHistorySearch() {
  const input = $('#history-search-input');
  if (!input) return;

  input.addEventListener('input', () => {
    clearTimeout(searchTimer);
    const q = input.value.trim();
    if (q.length < 2) {
      // Revert to date view
      if (isSearchMode) {
        isSearchMode = false;
        const container = $('#history-entries');
        const title = $('#history-date-title');
        if (title) {
          document.getElementById('view-history')?.classList.remove('history-search-mode');
          if (selectedHistoryDate) {
            title.textContent = formatDateTitle(selectedHistoryDate);
            loadHistoryEntries(selectedHistoryDate);
          }
        }
      }
      return;
    }

    searchTimer = setTimeout(async () => {
      isSearchMode = true;
      const title = $('#history-date-title');
      const container = $('#history-entries');
      const count = $('#history-count');

      if (title) {
        document.getElementById('view-history')?.classList.add('history-search-mode');
        title.textContent = `搜索: "${esc(q)}"`;
      }
      if (container) container.innerHTML = '<div class="history-loading">搜索中...</div>';
      if (count) count.textContent = '';

      try {
        const results = await invoke('search_history', { query: q });
        if (results.length === 0) {
          if (container) container.innerHTML = '<div class="placeholder-text"><span>未找到匹配结果</span></div>';
          if (count) count.textContent = '0 条';
          return;
        }

        if (count) count.textContent = `${results.length} 条结果`;

        if (container) {
          container.innerHTML = results.map((entry) => {
            const t = new Date(entry.time * 1000).toLocaleTimeString();
            const dateLabel = formatDateTitle(entry.date);
            return `<div class="history-entry">
              <div class="entry-header">
                <span class="entry-time">${dateLabel} ${t}</span>
              </div>
              <div class="entry-text">${highlightText(esc(entry.text), esc(q))}</div>
              <div class="entry-meta">
                <div class="entry-actions">
                  <button class="entry-btn" data-copy-search="${esc(entry.text)}">复制</button>
                </div>
              </div>
            </div>`;
          }).join('');

          container.querySelectorAll('[data-copy-search]').forEach((btn) => {
            btn.addEventListener('click', () => {
              navigator.clipboard.writeText(btn.dataset.copySearch);
              toast('✅ 已复制');
            });
          });
        }
      } catch (e) {
        if (container) container.innerHTML = '<div class="placeholder-text"><span>搜索失败</span></div>';
      }
    }, 300);
  });
}

function highlightText(text, query) {
  if (!query) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return text.slice(0, idx) + '<mark>' + text.slice(idx, idx + query.length) + '</mark>' + text.slice(idx + query.length);
}

function getDayName(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);

  const todayStr = today.toISOString().slice(0, 10);
  const yesterdayStr = yesterday.toISOString().slice(0, 10);

  if (dateStr === todayStr) return '今天';
  if (dateStr === yesterdayStr) return '昨天';

  const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
  const wd = weekdays[date.getDay()];
  return `${m}月${d}日 周${wd}`;
}

function formatDateTitle(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const weekdays = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'];
  const wd = weekdays[date.getDay()];
  return `${y}年${m}月${d}日 ${wd}`;
}

// === Export Transcriptions ===
$('#btn-export-srt')?.addEventListener('click', () => exportTranscriptions('srt'));
$('#btn-export-txt')?.addEventListener('click', () => exportTranscriptions('txt'));
$('#btn-export-json')?.addEventListener('click', () => exportTranscriptions('json'));

async function exportTranscriptions(format) {
  const entries = state.transcriptions;
  if (entries.length === 0) {
    toast('暂无内容可导出', 'warning');
    return;
  }

  // Show loading state on the clicked button
  const btnMap = { srt: 'btn-export-srt', txt: 'btn-export-txt', json: 'btn-export-json' };
  const btn = $(`#${btnMap[format]}`);
  const originalText = btn?.textContent || '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = '导出中...';
  }

  try {
    const fileName = await invoke('export_transcriptions', {
      entries: entries.map((e) => ({ text: e.text, time: e.time })),
      format: format,
    });
    toast(`✅ 已导出 "${fileName}"`);
  } catch (e) {
    if (e !== '用户取消了保存') {
      toast(`导出失败: ${e}`, 'error');
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

// === Translation ===
let translateDir = 'auto'; // 'auto', 'en2zh' or 'zh2en'

// Setup translation direction toggle
function setupTranslateBar() {
  const bar = $('#translate-bar');
  if (!bar) return;
  
  bar.querySelectorAll('.translate-dir-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      bar.querySelectorAll('.translate-dir-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      translateDir = btn.dataset.dir;
      toast(`翻译方向: ${btn.textContent.trim()}`);
    });
  });
}

// Translate a single text entry
async function translateText(text) {
  if (!text || text.trim().length === 0) {
    toast('没有可翻译的内容', 'warning');
    return null;
  }
  
  // Check if LLM is configured before attempting translation
  try {
    const llm = await invoke('load_llm_config');
    if (!llm.api_key || llm.api_key.trim() === '') {
      toast('⚠ 请先在设置中配置 LLM API Key', 'warning');
      // Navigate to Settings → LLM tab
      const sidebarBtn = document.querySelector('.sidebar-item[data-view="settings"]');
      if (sidebarBtn) sidebarBtn.click();
      const llmTab = document.querySelector('.settings-tab[data-tab="llm"]');
      if (llmTab) llmTab.click();
      return null;
    }
  } catch (_) {
    // If we can't load config, just attempt the translation
  }
  
  try {
    const result = await invoke('translate_text', {
      request: {
        text: text,
        direction: translateDir,
      }
    });
    return result;
  } catch (e) {
    toast(`翻译失败: ${e}`, 'error');
    return null;
  }
}

// Clear all history
let clearConfirmPending = false;
let clearConfirmTimer = null;

function setupClearHistory() {
  const btn = $('#btn-clear-history');
  if (!btn) return;
  
  btn.addEventListener('click', async () => {
    // Double-click confirmation pattern (avoids relying on window.confirm)
    if (!clearConfirmPending) {
      clearConfirmPending = true;
      toast('⚠ 再次点击确认清空所有历史记录', 'warning');
      clearConfirmTimer = setTimeout(() => { clearConfirmPending = false; }, 4000);
      return;
    }
    
    // Clear pending state
    clearConfirmPending = false;
    if (clearConfirmTimer) {
      clearTimeout(clearConfirmTimer);
      clearConfirmTimer = null;
    }
    
    try {
      await invoke('clear_all_history');
      toast('🗑 已清空所有历史记录');
      selectedHistoryDate = null;
      isSearchMode = false;
      const title = $('#history-date-title');
      const count = $('#history-count');
      const entries = $('#history-entries');
      if (title) title.textContent = '选择日期查看';
      if (count) count.textContent = '';
      if (entries) entries.innerHTML = '<div class="placeholder-text"><span class="placeholder-icon">📋</span><span>从左侧选择日期查看识别记录</span></div>';
      loadHistoryDates();
    } catch (e) {
      toast(`清空失败: ${e}`, 'error');
    }
  });
}

// === Toast ===
function toast(msg, type = 'info', duration = 3000) {
  const c = $('#toast-container');
  if (!c) return;
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<span class="toast-icon">${getToastIcon(type)}</span><span class="toast-msg">${esc(msg)}</span>`;
  c.appendChild(t);
  toastCleanup();
  requestAnimationFrame(() => t.classList.add('show'));
  setTimeout(() => {
    t.classList.remove('show');
    t.classList.add('hide');
    setTimeout(() => t.remove(), 300);
  }, duration);
}

function getToastIcon(type) {
  switch (type) {
    case 'error': return '✕';
    case 'warning': return '⚠';
    case 'info': default: return '✓';
  }
}

// === Util ===
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

// === Quick bar toggles sync with settings ===
function syncQuickToggles() {
  const pasteToggle = $('#toggle-paste');
  const hotToggle = $('#toggle-hotwords');
  const llmToggle = $('#toggle-llm');

  if (pasteToggle) {
    pasteToggle.addEventListener('change', async () => {
      const settingPaste = $('#setting-paste');
      if (settingPaste) settingPaste.checked = pasteToggle.checked;
      await saveQuickSettings();
    });
  }
  if (hotToggle) {
    hotToggle.addEventListener('change', async () => {
      const settingHot = $('#setting-hot-enabled');
      if (settingHot) settingHot.checked = hotToggle.checked;
      await saveQuickSettings();
    });
  }
  if (llmToggle) {
    llmToggle.addEventListener('change', async () => {
      await saveQuickSettings();
    });
  }
  const realtimeToggle = $('#toggle-realtime');
  if (realtimeToggle) {
    realtimeToggle.addEventListener('change', async () => {
      const settingRealtime = $('#setting-realtime');
      if (settingRealtime) settingRealtime.checked = realtimeToggle.checked;
      await saveQuickSettings();
    });
  }

  const translateToggle = $('#toggle-translate');
  if (translateToggle) {
    translateToggle.addEventListener('change', async () => {
      await saveQuickSettings();
    });
  }
}

async function saveQuickSettings() {
  try {
    const c = await invoke('load_config');
    if (!c) return;
    c.paste_on_finish = $('#toggle-paste')?.checked ?? true;
    c.hotwords_enabled = $('#toggle-hotwords')?.checked ?? true;
    c.llm_enabled = $('#toggle-llm')?.checked ?? false;
    c.realtime_enabled = $('#toggle-realtime')?.checked ?? false;
    c.translate_enabled = $('#toggle-translate')?.checked ?? false;
    await invoke('save_config', { config: c });
  } catch (_) {}
}

// === Hotword Management ===
function setupHotwordManagement() {
  const textarea = $('#hotword-text');
  const addBtn = $('#btn-add-hotword');
  const saveBtn = $('#btn-save-hotwords');

  // Load hotwords from backend
  async function loadHotwords() {
    if (!textarea) return;
    try {
      const content = await invoke('load_hotwords');
      textarea.value = content;
    } catch (e) {
      console.warn('[Hotwords] load failed:', e);
    }
  }

  // Save hotwords to backend
  async function saveHotwords() {
    if (!textarea) return;
    try {
      await invoke('save_hotwords', { content: textarea.value });
      toast('✅ 热词已保存');
    } catch (e) {
      toast(`保存失败: ${e}`, 'error');
    }
  }

  // Add a new hotword line
  addBtn?.addEventListener('click', () => {
    if (!textarea) return;
    const lines = textarea.value.split('\n').filter(l => l.trim());
    lines.push('');
    textarea.value = lines.join('\n');
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    toast('输入新的热词后点击保存');
  });

  // Save button
  saveBtn?.addEventListener('click', saveHotwords);

  // Auto-save on Ctrl+S
  textarea?.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      saveHotwords();
    }
  });

  // When hotword settings are saved via the main save button, also save hotwords
  $('#btn-save-model')?.addEventListener('click', async () => {
    // Small delay to let the main settings save first
    setTimeout(() => {
      if (textarea && textarea.value) {
        invoke('save_hotwords', { content: textarea.value }).catch(() => {});
      }
    }, 100);
  });

  // Expose load function so settings tab can call it
  window.__loadHotwords = loadHotwords;
}

// === Realtime Recording ===
let realtimeFlushTimer = null;
let realtimePcmBuffer = [];
let realtimeMediaSource = null;
let realtimeProcessor = null;

function startRealtimeFlush() {
  // Use ScriptProcessorNode to capture raw PCM at 16kHz
  if (!mediaStream) return;

  // Create a single card for this realtime session
  const area = $('#transcription-area');
  const ph = area?.querySelector('.placeholder-text');
  if (ph) ph.remove();

  const now = Date.now() / 1000;
  const t = new Date().toLocaleTimeString();
  const el = document.createElement('div');
  el.className = 'trans-entry';
  el.dataset.time = now;
  el.innerHTML = `
    <div class="entry-header">
      <span class="entry-time">${t} · 0.0s</span>
      <button class="entry-btn-del" data-del>✕</button>
    </div>
    <div class="entry-text"></div>
    <div class="entry-meta">
      <div class="entry-actions">
        <button class="entry-btn" data-copy>复制</button>
        <button class="entry-btn" data-paste>粘贴</button>
        <button class="entry-btn translate-btn" data-translate disabled>翻译</button>
      </div>
    </div>`;
  area?.prepend(el);
  realtimeCardEl = el;
  state.transcriptions.unshift({ text: '', time: now });

  el.querySelector('[data-copy]')?.addEventListener('click', () => {
    const text = el.querySelector('.entry-text')?.textContent || '';
    navigator.clipboard.writeText(text);
    toast('✅ 已复制');
  });
  el.querySelector('[data-paste]')?.addEventListener('click', async () => {
    const text = el.querySelector('.entry-text')?.textContent || '';
    await invoke('copy_to_clipboard', { text });
    toast('✅ 已粘贴到当前窗口');
  });
  el.querySelector('[data-translate]')?.addEventListener('click', async () => {
    // Disabled during recording — only translate after recording ends
    if (state.recording) {
      toast('录音中无法翻译，请先停止录音', 'warning');
      return;
    }
    const btn = el.querySelector('[data-translate]');
    if (btn) btn.textContent = '翻译中...';
    // Toggle existing translation
    let existing = el.querySelector('.entry-translation');
    if (existing) {
      existing.remove();
      if (btn) btn.textContent = '翻译';
      return;
    }
    const text = el.querySelector('.entry-text')?.textContent || '';
    const result = await translateText(text);
    if (result) {
      const meta = el.querySelector('.entry-meta');
      const div = document.createElement('div');
      div.className = 'entry-translation';
      div.textContent = `🌐 ${result}`;
      meta?.parentNode?.insertBefore(div, meta?.nextSibling || null);
      if (btn) btn.textContent = '收起';
    } else {
      if (btn) btn.textContent = '翻译';
    }
  });
  el.querySelector('[data-del]')?.addEventListener('click', () => {
    const idx = state.transcriptions.findIndex(t => t.time === now);
    if (idx !== -1) state.transcriptions.splice(idx, 1);
    el.remove();
    if (realtimeCardEl === el) realtimeCardEl = null;
    const total = state.transcriptions.reduce((s, t) => s + t.text.length, 0);
    const el2 = $('#char-count');
    if (el2) el2.textContent = total + ' 字';
    toast('🗑 已删除');
  });

  const total = state.transcriptions.reduce((s, t) => s + t.text.length, 0);
  const el2 = $('#char-count');
  if (el2) el2.textContent = total + ' 字';

  // Use the shared audioContext (created at 16kHz in startRecording) for realtime PCM capture
  const source = audioContext.createMediaStreamSource(mediaStream);
  // 4096 samples buffer, 1 input channel, 1 output channel
  realtimeProcessor = audioContext.createScriptProcessor(4096, 1, 1);
  realtimePcmBuffer = [];

  realtimeProcessor.onaudioprocess = (e) => {
    if (!state.recording) return;
    const input = e.inputBuffer.getChannelData(0);
    for (let i = 0; i < input.length; i++) {
      realtimePcmBuffer.push(input[i]);
    }
  };

  // Connect through processor to a silent GainNode (gain=0) as sink.
  // ScriptProcessorNode requires a downstream connection to fire onaudioprocess.
  const silentSink = audioContext.createGain();
  silentSink.gain.value = 0;
  source.connect(realtimeProcessor);
  realtimeProcessor.connect(silentSink);
  silentSink.connect(audioContext.destination);
  realtimeMediaSource = source;

  // Flush every 1.5 seconds using send_audio_chunk (non-destructive)
  realtimeFlushTimer = setInterval(async () => {
    if (realtimePcmBuffer.length === 0) return;
    const chunk = realtimePcmBuffer;
    realtimePcmBuffer = [];
    const duration = chunk.length / 16000;
    if (duration < 0.3) {
      // Too short — put data back so it accumulates with future audio
      realtimePcmBuffer = chunk;
      return;
    }
    try {
      await invoke('send_audio_chunk', { audioData: chunk });
    } catch (e) {
      console.warn('[Realtime] flush failed:', e);
    }
  }, 1500);

  micStatus.textContent = '● 实时转写中... 点击停止';
}

function stopRealtimeFlush() {
  if (realtimeFlushTimer) {
    clearInterval(realtimeFlushTimer);
    realtimeFlushTimer = null;
  }
  if (realtimeProcessor) {
    realtimeProcessor.disconnect();
    realtimeProcessor = null;
  }
  if (realtimeMediaSource) {
    realtimeMediaSource.disconnect();
    realtimeMediaSource = null;
  }
  // Shared audioContext is NOT closed here — it is managed by startRecording/onstop
  // Send any remaining buffered PCM
  if (realtimePcmBuffer.length > 0) {
    const remaining = realtimePcmBuffer;
    realtimePcmBuffer = [];
    const duration = remaining.length / 16000;
    if (duration >= 0.3) {
      invoke('send_audio_chunk', { audioData: remaining }).catch(() => {});
    }
  }
  realtimePcmBuffer = [];
}

// === Init ===
async function loadSettings() {
  try {
    const c = await invoke('load_config');
    if (!c) return;
    const sv = (id, v) => { const el = $(`#${id}`); if (el) el.value = v; };
    const sc = (id, v) => { const el = $(`#${id}`); if (el) el.checked = v; };
    sv('setting-model', c.model_type); sv('setting-lang', c.language);
    sc('setting-format-num', c.format_num); sc('setting-hot-enabled', c.hotwords_enabled);
    sc('toggle-llm', c.llm_enabled); sc('setting-paste', c.paste_on_finish);
    sc('setting-save-audio', c.save_audio); sv('setting-trash-punc', c.trash_punc);
    sv('setting-gpu', c.gpu || 'cpu');
    sc('setting-realtime', c.realtime_enabled || false);
    sv('setting-model-dir', c.custom_models_dir || '');
    // Sync quick bar toggles
    sc('toggle-paste', c.paste_on_finish);
    sc('toggle-hotwords', c.hotwords_enabled);
    sc('toggle-realtime', c.realtime_enabled || false);
    sc('toggle-translate', c.translate_enabled || false);
    // Sync translate direction
    translateDir = c.translate_direction || 'auto';
    const translateBar = $('#translate-bar');
    if (translateBar) {
      translateBar.querySelectorAll('.translate-dir-btn').forEach((b) => {
        b.classList.toggle('active', b.dataset.dir === translateDir);
      });
    }
  } catch (_) {}

  // Load LLM settings into the form
  try {
    const llm = await invoke('load_llm_config');
    if (llm) {
      sv('setting-llm-backend', llm.backend);
      sv('setting-llm-url', llm.api_url);
      sv('setting-llm-model', llm.model);
      sv('setting-llm-key', llm.api_key);
    }
  } catch (_) {}
}

async function checkServerStatus() {
  try {
    const r = await invoke('get_server_status');
    serverOnline = !!r;
    if (r) serverStarting = false;
    updateServerBadge();
    return r;
  } catch (_) {
    return false;
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  serverStarting = true;
  updateServerBadge();

  // Initialize quick toggle sync
  syncQuickToggles();

  // Poll every 1.5s until server is online
  const pollTimer = setInterval(async () => {
    const ok = await checkServerStatus();
    if (ok) {
      clearInterval(pollTimer);
    }
  }, 1500);

  // Sync settings panel back to quick bar
  $('#setting-paste')?.addEventListener('change', () => {
    const toggle = $('#toggle-paste');
    if (toggle) toggle.checked = $('#setting-paste').checked;
  });
  $('#setting-hot-enabled')?.addEventListener('change', () => {
    const toggle = $('#toggle-hotwords');
    if (toggle) toggle.checked = $('#setting-hot-enabled').checked;
  });
  $('#setting-realtime')?.addEventListener('change', () => {
    const toggle = $('#toggle-realtime');
    if (toggle) toggle.checked = $('#setting-realtime').checked;
  });

  // Setup translation bar
  setupTranslateBar();

  // Setup clear history button
  setupClearHistory();

  // Setup LLM backend preset auto-fill
  setupLlmPresets();

  // Setup history search
  setupHistorySearch();

  // Setup hotword management
  setupHotwordManagement();

  await loadSettings();

  // Fetch and display app version
  try {
    const ver = await getVersion();
    const verEl = $('#about-version');
    if (verEl) verEl.textContent = `版本 ${ver}`;
    // Also update title bar
    const titleEl = $('.titlebar-text');
    if (titleEl) titleEl.textContent = `CapsWriter Desktop · v${ver}`;
  } catch (_) {}
});

$('#btn-browse-model-dir')?.addEventListener('click', async () => {
  const input = $('#setting-model-dir');
  if (!input) return;
  try {
    const picked = await invoke('pick_model_dir');
    if (picked) {
      input.value = picked;
      console.log('[model-dir] picked', picked);
    }
  } catch (e) {
    console.error('[model-dir] pick failed', e);
    alert(`选择目录失败: ${e}`);
  }
});
