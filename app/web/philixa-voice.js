// =============================================================================
// PHILIXA 6.0: Voice Assistant Continuous Loop & Live Audio Streaming
// Multi-Tenant Authenticated WebSocket & Secure Voice Service Integration
// =============================================================================
// VAPI FEATURE FLAG: If meta tag voice-gateway-provider="vapi" is present,
// the Vapi Web SDK is used instead of the legacy WebSocket+Whisper pipeline.
// To rollback: change meta tag value to "legacy_live" or remove it entirely.
// =============================================================================

// --- Vapi Web SDK Integration (Side-by-Side, Non-Destructive) ---
const _vapiMeta = document.querySelector('meta[name="voice-gateway-provider"]');
const _useVapi = _vapiMeta && _vapiMeta.getAttribute("content") === "vapi";
const VAPI_PUBLIC_KEY = "974781c3-0fb7-4189-8de2-111dc187d794";
const VAPI_ASSISTANT_ID = "6763d0ce-bc3f-4c06-818a-27c515d9fec9"; // Riley assistant ID from dashboard

let _vapiInstance = null; // Holds the Vapi SDK instance when active

if (_useVapi) {
  // Load official Vapi HTML Script Tag SDK (exposes window.vapiSDK)
  const vapiScript = document.createElement("script");
  vapiScript.src = "https://cdn.jsdelivr.net/gh/VapiAI/html-script-tag@latest/dist/assets/index.js";
  vapiScript.defer = true;
  vapiScript.onload = () => {
    console.log("[Philixa Vapi] SDK loaded. Vapi mode active.");
    if (typeof window.vapiSDK === "undefined") {
      console.error("[Philixa Vapi] vapiSDK not found after SDK load.");
      return;
    }

    // Initialize Vapi with invisible built-in button (we use our own mic button)
    _vapiInstance = window.vapiSDK.run({
      apiKey: VAPI_PUBLIC_KEY,
      assistant: VAPI_ASSISTANT_ID,
      config: {
        position: "bottom-right",
        offset: "0px",
        width: "1px",
        height: "1px",
        idle:    { color: "transparent", type: "pill", title: "", subtitle: "", icon: "" },
        loading: { color: "transparent", type: "pill", title: "", subtitle: "", icon: "" },
        active:  { color: "transparent", type: "pill", title: "", subtitle: "", icon: "" },
      }
    });

    console.log("[Philixa Vapi] Instance created successfully.");

    // Mirror Vapi call state to Philixa UI states
    _vapiInstance.on("call-start", () => {
      console.log("[Philixa Vapi] Call started.");
      setVoiceState("listening");
    });

    _vapiInstance.on("speech-start", () => {
      setVoiceState("speaking");
    });

    _vapiInstance.on("speech-end", () => {
      setVoiceState("listening");
    });

    _vapiInstance.on("call-end", () => {
      console.log("[Philixa Vapi] Call ended.");
      setVoiceState("idle");
    });

    _vapiInstance.on("error", (err) => {
      console.error("[Philixa Vapi] Error:", err);
      if (typeof window.showToast === "function") {
        window.showToast("Voice connection error. Please try again.", true);
      }
      setVoiceState("idle");
    });

    // Override the mic button click handler for Vapi mode
    const fabBtn = document.getElementById("philixaVoiceBtn");
    if (fabBtn) {
      fabBtn.removeEventListener("click", handleVoiceClick);
      fabBtn.addEventListener("click", async () => {
        if (voiceState === "idle") {
          try {
            setVoiceState("thinking");
            _vapiInstance.start(VAPI_ASSISTANT_ID);
          } catch (e) {
            console.error("[Philixa Vapi] Failed to start call:", e);
            if (typeof window.showToast === "function") {
              window.showToast("Could not connect to Vapi. Check your internet.", true);
            }
            setVoiceState("idle");
          }
        } else {
          _vapiInstance.stop();
          setVoiceState("idle");
        }
      });
    }
  };
  vapiScript.onerror = () => {
    console.error("[Philixa Vapi] Failed to load Vapi SDK from CDN. Falling back to legacy mode.");
  };
  document.head.appendChild(vapiScript);
}
// --- End of Vapi Integration Block ---

let voiceState = "idle";
let voiceWs = null;
let voiceAudioContext = null;
let voiceWorkletNode = null;
let voiceAudioStream = null;
let conversationHistory = [];
let silenceTimeout = null;
const SILENCE_LIMIT_MS = 4000; // Decreased to 4000ms as requested by the user

// --- DOM Initialization ---
function initVoice() {
  const fabBtn = document.getElementById("philixaVoiceBtn");
  if (fabBtn) {
    fabBtn.addEventListener("click", handleVoiceClick);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initVoice);
} else {
  initVoice();
}

// --- UI State Management ---
function setVoiceState(state) {
  voiceState = state;
  const fabBtn = document.getElementById("philixaVoiceBtn");
  if (!fabBtn) return;

  const icon = fabBtn.querySelector(".copilot-icon");
  const text = fabBtn.querySelector(".copilot-text");

  fabBtn.className = "copilot-box";
  fabBtn.style.background = "";

  if (state === "idle") {
    if (icon) icon.textContent = "🎙️";
    if (text) text.textContent = "PHILIXA";
  } else if (state === "listening") {
    fabBtn.classList.add("listening");
    if (icon) icon.textContent = "🔴";
    if (text) text.textContent = "LISTENING...";
  } else if (state === "thinking") {
    fabBtn.classList.add("thinking");
    if (icon) icon.textContent = "🤔";
    if (text) text.textContent = "THINKING...";
  } else if (state === "speaking") {
    fabBtn.classList.add("speaking");
    if (icon) icon.textContent = "💬";
    if (text) text.textContent = "SPEAKING...";
  }
}

async function handleVoiceClick() {
  if (voiceState === "idle") {
    await startVoiceListening();
  } else if (voiceState === "listening") {
    await stopVoiceListening();
  }
}

// --- Auth & Helper Utilities ---
function getVoiceCsrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function voiceFetchWithAuth(url, options = {}) {
  if (typeof window.fetchWithAuth === "function") {
    return window.fetchWithAuth(url, options);
  }

  const opts = { ...options };
  opts.credentials = "include";
  opts.headers = { ...(opts.headers || {}) };

  const method = (opts.method || "GET").toUpperCase();
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrf = getVoiceCsrfToken();
    if (csrf && !opts.headers["X-CSRF-Token"]) {
      opts.headers["X-CSRF-Token"] = csrf;
    }
  }

  let response = await fetch(url, opts);

  if (response.status === 401 && !options._retried) {
    try {
      const refreshRes = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": getVoiceCsrfToken(),
        },
      });

      if (refreshRes.ok) {
        opts._retried = true;
        const newCsrf = getVoiceCsrfToken();
        if (newCsrf && ["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
          opts.headers["X-CSRF-Token"] = newCsrf;
        }
        response = await fetch(url, opts);
      }
    } catch (refreshErr) {
      console.warn("[Philixa Voice] Token refresh attempt failed:", refreshErr);
    }
  }

  return response;
}

async function mintWsTicket() {
  const response = await voiceFetchWithAuth("/api/v1/ws-ticket", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      errorDetail = payload.detail || errorDetail;
    } catch (_) {}
    throw new Error(`Authentication ticket generation failed: ${errorDetail}`);
  }

  const data = await response.json();
  const ticket = data.ticket || data.token;
  if (!ticket) {
    throw new Error("Invalid response from /api/v1/ws-ticket: missing ticket claim");
  }

  return ticket;
}

// --- Audio Resource Cleanup ---
function cleanupAudioResources() {
  if (silenceTimeout) {
    clearTimeout(silenceTimeout);
    silenceTimeout = null;
  }

  if (voiceWorkletNode) {
    try {
      voiceWorkletNode.disconnect();
    } catch (_) {}
    voiceWorkletNode = null;
  }

  if (voiceAudioContext) {
    try {
      if (voiceAudioContext.state !== "closed") {
        voiceAudioContext.close();
      }
    } catch (_) {}
    voiceAudioContext = null;
  }

  if (voiceAudioStream) {
    try {
      voiceAudioStream.getTracks().forEach((track) => track.stop());
    } catch (_) {}
    voiceAudioStream = null;
  }
}

// --- Voice Assistant Core Lifecycle ---
async function startVoiceListening() {
  if (voiceState === "listening") return;

  try {
    setVoiceState("listening");

    // 1. Mint short-lived WebSocket ticket
    let ticket;
    try {
      ticket = await mintWsTicket();
    } catch (ticketErr) {
      console.error("[Philixa Voice] Failed to mint WebSocket ticket:", ticketErr);
      if (typeof window.showToast === "function") {
        window.showToast("Voice authentication failed. Please re-login.", true);
      }
      setVoiceState("idle");
      return;
    }

    // 2. Obtain mic stream
    try {
      voiceAudioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 48000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (micErr) {
      console.error("[Philixa Voice] Microphone access error:", micErr);
      if (typeof window.showToast === "function") {
        window.showToast("Microphone access denied. Please grant mic permissions.", true);
      }
      setVoiceState("idle");
      return;
    }

    // 3. Audio graph setup
    voiceAudioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000 });
    const actualSampleRate = voiceAudioContext.sampleRate || 48000;

    try {
      await voiceAudioContext.audioWorklet.addModule("/static/pcm-processor.js");
    } catch (workletErr) {
      console.error("[Philixa Voice] AudioWorklet load failed:", workletErr);
      cleanupAudioResources();
      setVoiceState("idle");
      return;
    }

    const source = voiceAudioContext.createMediaStreamSource(voiceAudioStream);
    voiceWorkletNode = new AudioWorkletNode(voiceAudioContext, "pcm-processor");

    // 4. WebSocket setup
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/v1/live/transcribe?ticket=${encodeURIComponent(ticket)}&sample_rate=${actualSampleRate}&diarize=false`;

    voiceWs = new WebSocket(wsUrl);
    voiceWs.binaryType = "arraybuffer";

    voiceWs.onopen = () => {
      console.log("[Philixa Voice] WebSocket connected.");
      resetSilenceTimer();
    };

    voiceWs.onmessage = async (event) => {
      resetSilenceTimer();
      try {
        const data = JSON.parse(event.data);

        if (data.action === "processing") {
          return;
        }

        if (data.action === "error") {
          console.error("[Philixa Voice] Server error:", data.error);
          if (typeof window.showToast === "function") {
            window.showToast(data.error, true);
          }
          cleanupAudioResources();
          setVoiceState("idle");
          return;
        }

        if (data.action === "stopped") {
          if (data.confirmed && data.confirmed.trim()) {
            const transcript = data.confirmed.trim();
            console.log("[Philixa Voice] Heard:", transcript);
            await processUserTranscript(transcript);
          } else {
            if (data.error) {
              console.warn("[Philixa Voice] Transcribe warning/error:", data.error);
            }
            setVoiceState("idle");
          }
        }
      } catch (parseErr) {
        console.error("[Philixa Voice] Error parsing WebSocket message:", parseErr);
      }
    };

    voiceWs.onclose = (event) => {
      console.log(`[Philixa Voice] WebSocket closed (code: ${event.code})`);
      if (event.code === 1008) {
        console.error("[Philixa Voice] Policy violation (1008):", event.reason);
        if (typeof window.showToast === "function") {
          window.showToast(event.reason || "Voice auth failed: Session expired", true);
        }
        cleanupAudioResources();
        setVoiceState("idle");
        return;
      }

      if (voiceState === "listening" && event.code !== 1000) {
        cleanupAudioResources();
        setVoiceState("idle");
      }
    };

    voiceWs.onerror = (err) => {
      console.error("[Philixa Voice] WebSocket error:", err);
    };

    // 5. Pipe PCM chunks to WebSocket
    voiceWorkletNode.port.onmessage = (event) => {
      if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
        voiceWs.send(event.data);
      }
    };

    source.connect(voiceWorkletNode);
    voiceWorkletNode.connect(voiceAudioContext.destination);

  } catch (err) {
    console.error("[Philixa Voice] Listening start failed:", err);
    cleanupAudioResources();
    setVoiceState("idle");
  }
}

async function stopVoiceListening() {
  cleanupAudioResources();
  setVoiceState("thinking");

  if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
    voiceWs.send(JSON.stringify({ action: "stop" }));
  }
}

async function processUserTranscript(transcript) {
  if (!transcript || !transcript.trim()) {
    console.log("[Philixa Voice] Empty transcript ignored.");
    setVoiceState("idle");
    return;
  }

  try {
    setVoiceState("thinking");

    const response = await voiceFetchWithAuth("/api/v1/voice/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: transcript,
        conversation_history: conversationHistory,
      }),
    });

    if (!response.ok) throw new Error(`Chat API failed with status ${response.status}`);

    const data = await response.json();
    const aiResponseText = data.response;

    console.log("[Philixa Voice] AI Response:", aiResponseText);

    conversationHistory.push({ role: "user", content: transcript });
    conversationHistory.push({ role: "assistant", content: aiResponseText });

    if (conversationHistory.length > 10) {
      conversationHistory = conversationHistory.slice(-10);
    }

    await speakAIResponse(aiResponseText);
    
    if (data.meeting_id) {
      console.log("[Philixa Voice] Meeting ID received. Polling for confirmation...", data.meeting_id);
      
      const pollInterval = setInterval(async () => {
        try {
          const res = await voiceFetchWithAuth(`/api/v1/meeting-notes/${data.meeting_id}`);
          if (res.ok) {
            const meeting = await res.json();
            if (meeting.status === "client_identification_required") {
              clearInterval(pollInterval);
              console.log("[Philixa Voice] Client identification required popup triggered.");
              
              if (typeof state !== "undefined" && typeof els !== "undefined") {
                state.pendingConfirmationMeetingId = data.meeting_id;
                if (els.newClientName) els.newClientName.value = meeting.suggested_name || "";
                if (els.confirmPanel) els.confirmPanel.classList.remove("hidden");
                if (typeof window.showToast === "function") {
                  window.showToast("Please confirm the client name.", true);
                }
              }
            } else if (meeting.status === "processed" || meeting.status === "failed" || meeting.status === "manual_review_required") {
              clearInterval(pollInterval);
              if (meeting.status === "processed" && typeof window.refreshAll === "function") {
                  window.refreshAll();
              }
            }
          }
        } catch (e) {
          console.error("Polling error in voice assistant:", e);
        }
      }, 2000);
    }
  } catch (err) {
    console.error("[Philixa Voice] Process error:", err);
    if (typeof window.showToast === "function") {
      window.showToast("Voice assistant error processing request.", true);
    }
    setVoiceState("idle");
  }
}

async function speakAIResponse(text) {
  try {
    setVoiceState("speaking");

    const response = await voiceFetchWithAuth("/api/v1/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    });

    if (!response.ok) throw new Error(`TTS API failed with status ${response.status}`);

    const blob = await response.blob();
    if (!blob || blob.size === 0) throw new Error("Empty audio stream from TTS API");

    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);

    audio.onended = () => {
      URL.revokeObjectURL(audioUrl);
      const lower = text.toLowerCase();
      if (lower.includes("?") || lower.includes("save") || lower.includes("karein") || lower.includes("bataiye")) {
        startVoiceListening();
      } else {
        setVoiceState("idle");
      }
    };

    audio.onerror = (err) => {
      console.error("[Philixa Voice] Playback error:", err);
      URL.revokeObjectURL(audioUrl);
      setVoiceState("idle");
    };

    await audio.play();
  } catch (err) {
    console.error("[Philixa Voice] TTS error:", err);
    setVoiceState("idle");
  }
}

function resetSilenceTimer() {
  if (silenceTimeout) clearTimeout(silenceTimeout);
  silenceTimeout = setTimeout(() => {
    console.log("[Philixa Voice] Silence detected. Stopping recording.");
    if (voiceState === "listening") {
      stopVoiceListening();
    }
  }, SILENCE_LIMIT_MS);
}

