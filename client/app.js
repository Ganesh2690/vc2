// Voice Agent — React UI via CDN + Babel Standalone
// No build step required. Loaded by index.html.

const { useState, useEffect, useRef, useCallback } = React;

// ─── Constants ───────────────────────────────────────────────────────────────

const STATE_COLOURS = {
  INITIALIZING:       "#6366f1",
  READY:              "#22c55e",
  LISTENING:          "#22c55e",
  USER_SPEAKING:      "#f59e0b",
  THINKING_PAUSE:     "#f59e0b",
  PROCESSING:         "#3b82f6",
  SPEAKING:           "#8b5cf6",
  INTERRUPT_CANDIDATE:"#ef4444",
  INTERRUPTED:        "#ef4444",
  DEGRADED:           "#f97316",
  SHUTDOWN:           "#6b7280",
};

const MAX_TRANSCRIPT_LINES = 80;

// ─── Utilities ───────────────────────────────────────────────────────────────

async function fetchToken(identity) {
  const res = await fetch(`/token?identity=${encodeURIComponent(identity)}`);
  if (!res.ok) throw new Error(`Token fetch failed: ${res.status}`);
  return res.json(); // { token, url, room }
}

async function publishClientReady(room) {
  if (!room?.localParticipant) return;

  const payload = new TextEncoder().encode(JSON.stringify({ type: "client_ready" }));
  await room.localParticipant.publishData(payload, { reliable: true, topic: "app" });
}

// ─── Components ──────────────────────────────────────────────────────────────

function StateBadge({ state }) {
  const colour = STATE_COLOURS[state] || "#6b7280";
  return (
    <span style={{
      display: "inline-block",
      padding: "2px 10px",
      borderRadius: "9999px",
      background: colour + "28",
      border: `1px solid ${colour}`,
      color: colour,
      fontWeight: 600,
      fontSize: "0.8rem",
      letterSpacing: "0.04em",
    }}>
      {state || "—"}
    </span>
  );
}

function MetricsBar({ metrics }) {
  const pairs = [
    ["STT", metrics.stt_latency_ms],
    ["TTFT", metrics.llm_ttft_ms],
    ["TTS", metrics.tts_first_audio_ms],
    ["E2E", metrics.e2e_latency_ms],
  ];
  return (
    <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
      {pairs.map(([label, value]) => (
        <div key={label} style={{ fontSize: "0.78rem", color: "#9ca3af" }}>
          <span style={{ color: "#d1d5db", fontWeight: 600 }}>{label}: </span>
          {value != null ? `${Math.round(value)} ms` : "—"}
        </div>
      ))}
    </div>
  );
}

function TranscriptLine({ role, text, final }) {
  const isUser = role === "user";
  return (
    <div style={{
      padding: "8px 12px",
      borderRadius: "8px",
      maxWidth: "85%",
      alignSelf: isUser ? "flex-end" : "flex-start",
      background: isUser ? "#1e3a5f" : "#1a1a2e",
      border: isUser ? "1px solid #2563eb44" : "1px solid #7c3aed44",
      opacity: final ? 1 : 0.7,
      marginBottom: "4px",
    }}>
      <div style={{ fontSize: "0.7rem", color: isUser ? "#60a5fa" : "#a78bfa", marginBottom: "2px" }}>
        {isUser ? "You" : "Agent"}{!final ? " (live)" : ""}
      </div>
      <div style={{ fontSize: "0.95rem", lineHeight: 1.5 }}>{text}</div>
    </div>
  );
}

// ─── Main App ────────────────────────────────────────────────────────────────

function App() {
  const [status, setStatus] = useState("disconnected"); // disconnected | connecting | connected | error
  const [agentState, setAgentState] = useState("—");
  const [metrics, setMetrics] = useState({});
  const [transcript, setTranscript] = useState([]); // [{role, text, final, id}]
  const [errorMsg, setErrorMsg] = useState("");

  const roomRef = useRef(null);
  const remoteAudioRef = useRef(null);
  const transcriptEndRef = useRef(null);
  const micEnabledRef = useRef(false);
  const waitingForGreetingRef = useRef(false);
  const micFallbackTimerRef = useRef(null);
  const lineIdRef = useRef(0);
  const liveLineRef = useRef({}); // role → {id, text}

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const clearMicFallbackTimer = useCallback(() => {
    if (micFallbackTimerRef.current) {
      clearTimeout(micFallbackTimerRef.current);
      micFallbackTimerRef.current = null;
    }
  }, []);

  const enableMicrophone = useCallback(async (reason) => {
    const room = roomRef.current;
    if (!room || micEnabledRef.current) return;

    try {
      await room.localParticipant.setMicrophoneEnabled(true);
      micEnabledRef.current = true;
      waitingForGreetingRef.current = false;
      clearMicFallbackTimer();
      console.info(`Microphone enabled: ${reason}`);
    } catch (err) {
      console.error("Microphone error:", err);
      setErrorMsg(`Microphone permission failed: ${err}`);
    }
  }, [clearMicFallbackTimer]);

  // ── Data channel message handler ──────────────────────────────────────────
  const handleDataMessage = useCallback((payload) => {
    let msg;
    try {
      msg = JSON.parse(new TextDecoder().decode(payload));
    } catch { return; }

    if (msg.type === "state") {
      setAgentState(msg.current || msg.new_state || "—");
    } else if (msg.type === "metric") {
      setMetrics(prev => ({ ...prev, [msg.metric]: msg.value }));
    } else if (msg.type === "ready_for_user") {
      if (waitingForGreetingRef.current) {
        enableMicrophone("greeting_complete");
      }
    } else if (msg.type === "transcript") {
      const { role, text, final } = msg;
      if (!text) return;

      setTranscript(prev => {
        const live = liveLineRef.current[role];
        if (!final && live) {
          // Update existing live line
          return prev.map(l => l.id === live.id ? { ...l, text } : l);
        }
        if (final && live) {
          // Finalise live line
          liveLineRef.current[role] = null;
          return prev.map(l => l.id === live.id ? { ...l, text, final: true } : l);
        }
        // New line
        const id = ++lineIdRef.current;
        if (!final) liveLineRef.current[role] = { id, text };
        const newLine = { role, text, final: !!final, id };
        const updated = [...prev, newLine];
        return updated.length > MAX_TRANSCRIPT_LINES
          ? updated.slice(updated.length - MAX_TRANSCRIPT_LINES)
          : updated;
      });
    }
  }, [enableMicrophone]);

  // ── Connect ───────────────────────────────────────────────────────────────
  const connect = useCallback(async () => {
    setStatus("connecting");
    setErrorMsg("");
    setTranscript([]);
    setMetrics({});
    micEnabledRef.current = false;
    waitingForGreetingRef.current = true;
    clearMicFallbackTimer();
    liveLineRef.current = {};

    try {
      const { token, url, room: roomName } = await fetchToken(
        `user-${Math.random().toString(36).slice(2, 8)}`
      );

      const room = new LivekitClient.Room({
        adaptiveStream: false,
        dynacast: false,
        audioCaptureDefaults: {
          autoGainControl: false,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      roomRef.current = room;

      room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {
        if (track.kind !== LivekitClient.Track.Kind.Audio) return;
        const element = track.attach();
        element.autoplay = true;
        element.playsInline = true;
        element.style.display = "none";
        remoteAudioRef.current?.appendChild(element);
        element.play?.().catch(err => console.warn("Remote audio play blocked:", err));
      });
      room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {
        track.detach().forEach(element => element.remove());
      });
      room.on(LivekitClient.RoomEvent.DataReceived, handleDataMessage);
      room.on(LivekitClient.RoomEvent.Disconnected, () => {
        setStatus("disconnected");
        if (remoteAudioRef.current) remoteAudioRef.current.innerHTML = "";
        micEnabledRef.current = false;
        waitingForGreetingRef.current = false;
        clearMicFallbackTimer();
        setAgentState("—");
      });

      await room.connect(url, token);
      await publishClientReady(room);

      setStatus("connected");
      setAgentState("READY");
      micFallbackTimerRef.current = setTimeout(() => {
        if (waitingForGreetingRef.current) {
          enableMicrophone("greeting_timeout");
        }
      }, 12000);
    } catch (err) {
      console.error("Connection error:", err);
      setErrorMsg(String(err));
      setStatus("error");
      micEnabledRef.current = false;
      waitingForGreetingRef.current = false;
      clearMicFallbackTimer();
    }
  }, [clearMicFallbackTimer, enableMicrophone, handleDataMessage]);

  // ── Disconnect ────────────────────────────────────────────────────────────
  const disconnect = useCallback(async () => {
    if (roomRef.current) {
      await roomRef.current.disconnect();
      roomRef.current = null;
    }
    if (remoteAudioRef.current) remoteAudioRef.current.innerHTML = "";
    micEnabledRef.current = false;
    waitingForGreetingRef.current = false;
    clearMicFallbackTimer();
    setStatus("disconnected");
    setAgentState("—");
  }, [clearMicFallbackTimer]);

  // ─── Render ───────────────────────────────────────────────────────────────
  const connected = status === "connected";

  return (
    <div style={{
      display: "flex", flexDirection: "column", height: "100vh",
      padding: "16px", gap: "12px",
    }}>

      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 16px", background: "#16161e",
        borderRadius: "10px", border: "1px solid #2a2a3a",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span style={{ fontSize: "1.1rem", fontWeight: 700, color: "#e2e2e8" }}>
            🎙 Voice Agent
          </span>
          <StateBadge state={agentState} />
        </div>
        <button
          onClick={connected ? disconnect : connect}
          disabled={status === "connecting"}
          style={{
            padding: "8px 20px", borderRadius: "8px", border: "none",
            fontWeight: 600, fontSize: "0.9rem", cursor: "pointer",
            background: connected ? "#7f1d1d" : "#1d4ed8",
            color: "#fff",
            opacity: status === "connecting" ? 0.6 : 1,
          }}
        >
          {status === "connecting" ? "Connecting…" : connected ? "Disconnect" : "Connect"}
        </button>
      </div>

      {/* Metrics bar */}
      {connected && (
        <div style={{
          padding: "10px 16px", background: "#16161e",
          borderRadius: "8px", border: "1px solid #2a2a3a",
        }}>
          <MetricsBar metrics={metrics} />
        </div>
      )}

      {/* Error */}
      {errorMsg && (
        <div style={{
          padding: "10px 14px", background: "#7f1d1d28",
          border: "1px solid #ef444466", borderRadius: "8px",
          color: "#fca5a5", fontSize: "0.85rem",
        }}>
          {errorMsg}
        </div>
      )}

      {/* Transcript */}
      <div style={{
        flex: 1, overflowY: "auto", display: "flex", flexDirection: "column",
        gap: "6px", padding: "12px", background: "#13131a",
        borderRadius: "10px", border: "1px solid #2a2a3a",
      }}>
        {transcript.length === 0 && (
          <div style={{ color: "#4b5563", fontSize: "0.9rem", margin: "auto", textAlign: "center" }}>
            {connected ? "Say something to start…" : "Click Connect to begin"}
          </div>
        )}
        {transcript.map(line => (
          <TranscriptLine key={line.id} role={line.role} text={line.text} final={line.final} />
        ))}
        <div ref={transcriptEndRef} />
      </div>

      {/* Footer */}
      <div style={{ textAlign: "center", fontSize: "0.72rem", color: "#374151" }}>
        LiveKit · Pipecat · Silero VAD · distil-large-v3 · gpt-5.4-nano-2026-03-17 · Piper TTS
      </div>
      <div ref={remoteAudioRef} aria-hidden="true" />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
