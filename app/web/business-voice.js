// Authenticated microphone -> existing PCM transcription backend. No legacy CRM calls.
window.createBusinessVoice = ({ onTranscript, onStatus, onActive }) => {
  let generation = 0, socket, stream, context, worklet, timer, watchdog;
  let phase = 'idle', started = 0, lastSpeech = 0;
  const releaseMic = () => {
    clearInterval(timer); timer = null;
    if (worklet) { worklet.disconnect(); worklet = null; }
    if (stream) { stream.getTracks().forEach(track => track.stop()); stream = null; }
    if (context) { context.close().catch(() => {}); context = null; }
  };
  const cancel = () => {
    generation++; releaseMic(); clearTimeout(watchdog);
    if (socket) { socket.close(); socket = null; }
    phase = 'idle'; onActive(false);
  };
  const fail = message => { cancel(); onStatus(message); };
  const stop = () => {
    if (phase !== 'listening') return;
    releaseMic(); phase = 'transcribing'; onStatus('Aapki baat samajh raha hoon…');
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ action: 'stop' }));
    else fail('Voice connection nahi bani. Dobara try karein.');
  };
  const start = async () => {
    if (phase === 'listening') { stop(); return; }
    if (phase !== 'idle') { cancel(); onStatus('Voice ruk gayi.'); return; }
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      onStatus('Is browser mein microphone available nahi hai. Message type karein.'); return;
    }
    phase = 'starting'; onActive(true); onStatus('Mic permission dein…');
    const id = ++generation;
    try {
      const captured = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      if (id !== generation) { captured.getTracks().forEach(track => track.stop()); return; }
      stream = captured;
      context = new (window.AudioContext || window.webkitAudioContext)();
      await context.resume();
      await context.audioWorklet.addModule('/static/pcm-processor.js');
      if (id !== generation) return;
      const res = await window.fetchWithAuth('/api/v1/ws-ticket', { method: 'POST' });
      if (!res.ok) throw new Error('auth');
      const data = await res.json();
      if (id !== generation) return;
      const ticket = data.ticket || data.token;
      if (!ticket) throw new Error('auth');
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/v1/live/transcribe?ticket=${encodeURIComponent(ticket)}&sample_rate=${context.sampleRate}&diarize=false`);
      let finalReceived = false;
      watchdog = setTimeout(() => { if (id === generation) fail('Voice service ne waqt par jawab nahi diya. Dobara try karein.'); }, 90000);
      socket.onopen = () => {
        if (id !== generation) return;
        worklet = new AudioWorkletNode(context, 'pcm-processor');
        worklet.port.onmessage = event => {
          if (phase !== 'listening' || socket?.readyState !== WebSocket.OPEN) return;
          const pcm = new Int16Array(event.data);
          let sum = 0; for (const sample of pcm) sum += sample * sample;
          if (Math.sqrt(sum / pcm.length) > 700) lastSpeech = Date.now();
          socket.send(event.data);
        };
        context.createMediaStreamSource(stream).connect(worklet);
        worklet.connect(context.destination);
        phase = 'listening'; started = Date.now(); lastSpeech = 0;
        onStatus('Boliyega… Baat khatam ho to mic dabayein, ya 3 second chup rahein.');
        timer = setInterval(() => {
          const now = Date.now();
          if ((lastSpeech && now - lastSpeech > 3000) || now - started > 30000) stop();
          else if (!lastSpeech && now - started > 10000) fail('Awaaz nahi mili. Mic dobara dabakar boliyega.');
        }, 250);
      };
      socket.onmessage = event => {
        if (id !== generation) return;
        let data; try { data = JSON.parse(event.data); } catch { return; }
        if (data.action === 'error' || data.action === 'timeout') { fail('Awaaz samajh nahi aayi. Dobara bolein ya type karein.'); return; }
        if (data.action === 'stopped') {
          finalReceived = true;
          const text = (data.confirmed || '').trim(); cancel();
          if (text) onTranscript(text.slice(0, 4000));
          else onStatus('Awaaz samajh nahi aayi. Dobara bolein ya type karein.');
        }
      };
      socket.onerror = () => { if (id === generation) fail('Voice connection fail hui. Dobara try karein.'); };
      socket.onclose = () => { if (id === generation && !finalReceived) fail('Voice connection band hui. Dobara try karein.'); };
    } catch (error) {
      if (id === generation) fail(error.name === 'NotAllowedError' ? 'Mic permission nahi mili. Browser settings mein allow karein.' : 'Mic start nahi hua. Dobara try karein ya type karein.');
    }
  };
  return { toggle: start, cancel };
};
