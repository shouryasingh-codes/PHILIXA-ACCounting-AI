// Web Speech API Implementation for Fast Dictation
// Completely isolated from the Whisper/Live Recording logic

document.addEventListener("DOMContentLoaded", () => {
  const tabFastDictationBtn = document.getElementById("tabFastDictationBtn");
  const viewFastDictation = document.getElementById("viewFastDictation");
  
  const startDictationBtn = document.getElementById("startDictationBtn");
  const stopDictationBtn = document.getElementById("stopDictationBtn");
  const dictationStatusText = document.getElementById("dictationStatusText");
  const dictationResult = document.getElementById("dictationResult");
  
  if (!tabFastDictationBtn && !startDictationBtn) {
    return; // Fast dictation controls not present on current layout
  }
  
  // Elements from existing app to switch tabs and dump text
  const viewText = document.getElementById("viewText");
  const viewAudio = document.getElementById("viewAudio");
  const viewLive = document.getElementById("viewLive");
  const tabTextBtn = document.getElementById("tabTextBtn");
  const tabAudioBtn = document.getElementById("tabAudioBtn");
  const tabLiveBtn = document.getElementById("tabLiveBtn");
  
  const rawNotes = document.getElementById("rawNotes");

  let recognition = null;
  let finalTranscript = "";

  let isRecording = false;

  // Check if browser supports Web Speech API
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  
  if (!SpeechRecognition) {
    dictationStatusText.textContent = "❌ Not supported in this browser (Use Chrome)";
    startDictationBtn.disabled = true;
  } else {
    recognition = new SpeechRecognition();
    recognition.continuous = false; // Android bug fix: set to false, auto-restart on end
    recognition.interimResults = true;
    recognition.lang = 'en-IN'; 

    recognition.onstart = () => {
      dictationStatusText.textContent = "🔴 Recording... Speak now";
      startDictationBtn.disabled = true;
      stopDictationBtn.disabled = false;
    };

    recognition.onerror = (event) => {
      console.error("Speech recognition error", event.error);
      if (event.error !== 'no-speech') {
        dictationStatusText.textContent = `❌ Error: ${event.error}`;
        startDictationBtn.disabled = false;
        stopDictationBtn.disabled = true;
        isRecording = false;
      }
    };

    recognition.onend = () => {
      if (isRecording) {
        // Auto-restart to simulate continuous recording safely
        try { recognition.start(); } catch(e) {}
      } else {
        dictationStatusText.textContent = "⏸ Ready (Web Speech API)";
        startDictationBtn.disabled = false;
        stopDictationBtn.disabled = true;
      }
    };

    recognition.onresult = (event) => {
      let currentFinal = "";
      let interimTranscript = "";
      for (let i = 0; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          currentFinal += event.results[i][0].transcript + " ";
        } else {
          interimTranscript += event.results[i][0].transcript;
        }
      }
      
      // Because continuous=false, currentFinal is just the current finished sentence.
      // Append it to our global finalTranscript immediately.
      if (currentFinal) {
         finalTranscript += currentFinal;
      }
      
      dictationResult.innerHTML = `
        <span style="font-weight:600; color:var(--ink);">${finalTranscript}</span>
        <span style="color:var(--muted); font-style:italic;">${interimTranscript}</span>
      `;
    };
  }

  // --- UI Interactions ---

  if (tabFastDictationBtn) {
    tabFastDictationBtn.addEventListener("click", () => {
      tabFastDictationBtn.classList.add("active");
      if (viewFastDictation) {
        viewFastDictation.classList.remove("hidden");
        viewFastDictation.style.display = "block";
      }
      
      [tabTextBtn, tabAudioBtn, tabLiveBtn].forEach(btn => {
        if(btn) btn.classList.remove("active");
      });
      
      [viewText, viewAudio, viewLive].forEach(view => {
        if(view) {
          view.classList.add("hidden");
          view.classList.remove("active");
          view.style.display = "none";
        }
      });
    });
  }

  [tabTextBtn, tabAudioBtn, tabLiveBtn].forEach(btn => {
    if(!btn) return;
    btn.addEventListener("click", () => {
      if (tabFastDictationBtn) tabFastDictationBtn.classList.remove("active");
      if (viewFastDictation) {
        viewFastDictation.classList.add("hidden");
        viewFastDictation.style.display = "none";
      }
      if (recognition && isRecording) {
          isRecording = false;
          recognition.stop();
      }
    });
  });

  if (startDictationBtn) {
    startDictationBtn.addEventListener("click", () => {
      if (recognition) {
        try {
          finalTranscript = "";
          if (dictationResult) dictationResult.innerHTML = "";
          isRecording = true;
          recognition.start();
        } catch (e) {
          console.error(e);
        }
      }
    });
  }

  if (stopDictationBtn) {
    stopDictationBtn.addEventListener("click", () => {
      if (recognition) {
        isRecording = false;
        recognition.stop();
        
        if (finalTranscript.trim()) {
          const textToPaste = finalTranscript.trim();
          if (rawNotes) rawNotes.value = textToPaste;
          if (tabTextBtn) tabTextBtn.click();
        }
      }
    });
  }
});
