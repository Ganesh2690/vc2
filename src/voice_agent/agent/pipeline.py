"""Pipecat pipeline wiring — connects all stages into a linear chain.

Pipeline order:
  LiveKitTransport.input()          ← VAD (SileroVADAnalyzer) embedded
  → BargeInController               ← barge-in confirmation + arm/disarm
  → FasterWhisperSTTService         ← audio → transcript (with Smart Turn)
    → ConversationController          ← state machine transitions + data-channel events
    → MetricsCollector                ← latency timestamps
  → OpenAILLMContextAggregator.user()← accumulate user messages
  → OpenAILLMService                ← streaming LLM tokens
  → TextChunker                     ← token stream → TTS-ready phrases
  → PiperTTSService                 ← phrases → audio
  → LiveKitTransport.output()       ← audio → WebRTC playback
  → OpenAILLMContextAggregator.assistant() ← accumulate assistant response
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import structlog
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    StartFrame,
    TextFrame,
    TranscriptionFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContext,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport
from pipecat.turns.user_start import TranscriptionUserTurnStartStrategy
from pipecat.turns.user_stop import ExternalUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from voice_agent.agent.barge_in import BargeInController
from voice_agent.agent.state_machine import ConversationState, ConversationStateMachine
from voice_agent.config import AgentSettings
from voice_agent.frames import InterruptFrame, StateChangeFrame
from voice_agent.llm.chunker import TextChunker
from voice_agent.memory.session_memory import SessionMemory
from voice_agent.metrics.collector import MetricsCollector
from voice_agent.stt.faster_whisper_adapter import FasterWhisperSTTService
from voice_agent.tts.piper_adapter import PiperTTSService

log = structlog.get_logger(__name__)

_EMPTY_ASSISTANT_FALLBACK = "I'm sorry, I didn't get a response. Please try again."


# ────────────────────────────────────────────────────────────────────────────
# Conversation controller — state machine proxy inside the pipeline
# ────────────────────────────────────────────────────────────────────────────

class ConversationController(FrameProcessor):
    """Listens to pipeline events and drives the state machine.

    Also publishes state, transcript, and metric events to the browser via
    the LiveKit data channel.
    """

    def __init__(
        self,
        state_machine: ConversationStateMachine,
        memory: SessionMemory,
        transport: LiveKitTransport,
        session_id: str,
    ) -> None:
        super().__init__()
        self._sm = state_machine
        self._memory = memory
        self._transport = transport
        self._session_id = session_id
        self._pending_user_text: str = ""
        self._pending_assistant_chunks: list[str] = []
        self._assistant_interrupted = False

    # ──────────────────────────────────────────────── frame processing ──

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if direction == FrameDirection.DOWNSTREAM:
            await self._handle_downstream(frame)
        else:
            await self._handle_upstream(frame)

        await self.push_frame(frame, direction)

    async def _handle_downstream(self, frame: Frame) -> None:
        sm = self._sm

        if isinstance(frame, StartFrame):
            sm.try_transition(ConversationState.READY)
            sm.try_transition(ConversationState.LISTENING)

        elif isinstance(frame, (UserStartedSpeakingFrame, VADUserStartedSpeakingFrame)):
            sm.try_transition(ConversationState.USER_SPEAKING)

        elif isinstance(frame, (UserStoppedSpeakingFrame, VADUserStoppedSpeakingFrame)):
            sm.try_transition(ConversationState.THINKING_PAUSE)

        elif isinstance(frame, TranscriptionFrame):
            self._pending_user_text = frame.text
            self._memory.append_user(frame.text)
            self._assistant_interrupted = False
            self._pending_assistant_chunks = []
            sm.try_transition(ConversationState.PROCESSING)
            await self._publish(
                "transcript",
                {"role": "user", "text": frame.text, "final": True},
            )

        elif isinstance(frame, InterruptFrame):
            self._assistant_interrupted = True
            sm.try_transition(ConversationState.INTERRUPTED)

        elif isinstance(frame, TTSStartedFrame):
            sm.try_transition(ConversationState.SPEAKING)

        elif isinstance(frame, TTSStoppedFrame):
            # Commit assistant turn only if not interrupted
            if not self._assistant_interrupted and self._pending_assistant_chunks:
                text = " ".join(self._pending_assistant_chunks).strip()
                if text:
                    self._memory.append_assistant(text)
                    await self._publish(
                        "transcript",
                        {"role": "assistant", "text": text, "final": True},
                    )
            self._pending_assistant_chunks = []
            sm.try_transition(ConversationState.LISTENING)

    async def _handle_upstream(self, frame: Frame) -> None:
        sm = self._sm

        if isinstance(frame, InterruptionFrame):
            if sm.state == ConversationState.SPEAKING:
                sm.try_transition(ConversationState.INTERRUPT_CANDIDATE)
                sm.try_transition(ConversationState.INTERRUPTED)

        elif isinstance(frame, BotStartedSpeakingFrame):
            if sm.state == ConversationState.THINKING_PAUSE:
                sm.try_transition(ConversationState.PROCESSING)
            sm.try_transition(ConversationState.SPEAKING)

        elif isinstance(frame, BotStoppedSpeakingFrame):
            if sm.state == ConversationState.SPEAKING:
                sm.try_transition(ConversationState.LISTENING)
            log.info("ready_for_user", state=sm.state.value)
            await self._publish(
                "ready_for_user",
                {"session_id": self._session_id, "state": sm.state.value},
            )

    async def _publish(self, event_type: str, payload: dict) -> None:
        """Send a JSON event to the browser via LiveKit data channel."""
        try:
            msg = json.dumps(
                {"type": event_type, "ts": time.time(), **payload}
            )
            await self._transport.send_message(msg)
        except Exception as exc:
            log.debug("data_channel_send_error", error=str(exc))

    async def publish_state(self, previous: ConversationState, new: ConversationState) -> None:
        """Called by the state machine on every transition."""
        await self._publish(
            "state",
            {
                "previous": previous.value,
                "current": new.value,
                "session_id": self._session_id,
            },
        )
        await self.push_frame(
            StateChangeFrame(
                previous_state=previous.value,
                new_state=new.value,
                timestamp=time.time(),
            ),
            FrameDirection.DOWNSTREAM,
        )


class AssistantResponsePublisher(FrameProcessor):
    """Publishes assistant LLM/TTS text to the browser and session memory."""

    def __init__(
        self,
        memory: SessionMemory,
        transport: LiveKitTransport,
        llm_context: LLMContext | None = None,
    ) -> None:
        super().__init__()
        self._memory = memory
        self._transport = transport
        self._llm_context = llm_context
        self._chunks: list[str] = []
        self._in_llm_response = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, LLMFullResponseStartFrame):
                self._chunks = []
                self._in_llm_response = True
                log.info("assistant_response_start")

            elif isinstance(frame, TextFrame) and frame.text.strip():
                text = frame.text.strip()
                self._chunks.append(text)
                log.info("assistant_text_chunk", chars=len(text), text=text[:80])
                await self._publish(
                    {"role": "assistant", "text": text, "final": False},
                )

            elif isinstance(frame, LLMFullResponseEndFrame):
                if not self._chunks:
                    await self._emit_empty_response_fallback(direction)
                await self._finalize()
                self._in_llm_response = False

        elif direction == FrameDirection.UPSTREAM:
            if (
                isinstance(frame, (BotStoppedSpeakingFrame, TTSStoppedFrame))
                and self._chunks
                and not self._in_llm_response
            ):
                await self._finalize()

        await self.push_frame(frame, direction)

    async def _emit_empty_response_fallback(self, direction: FrameDirection) -> None:
        text = _EMPTY_ASSISTANT_FALLBACK
        self._chunks = [text]
        log.warning("assistant_empty_response_fallback", text=text)
        await self._publish({"role": "assistant", "text": text, "final": False})
        await self.push_frame(TextFrame(text=text), direction)

    async def _finalize(self) -> None:
        text = " ".join(self._chunks).strip()
        if not text:
            return

        self._memory.append_assistant(text)
        if self._llm_context is not None:
            self._llm_context.add_message({"role": "assistant", "content": text})
        log.info("assistant_response_final", chars=len(text), text=text[:120])
        await self._publish({"role": "assistant", "text": text, "final": True})
        self._chunks = []

    async def _publish(self, payload: dict) -> None:
        try:
            msg = json.dumps({"type": "transcript", "ts": time.time(), **payload})
            await self._transport.send_message(msg)
        except Exception as exc:
            log.debug("data_channel_send_error", error=str(exc))


# ────────────────────────────────────────────────────────────────────────────
# Pipeline factory
# ────────────────────────────────────────────────────────────────────────────

async def build_pipeline(
    settings: AgentSettings,
    token: str,
    room_name: str,
    session_id: str,
) -> tuple[PipelineTask, ConversationStateMachine, SessionMemory, MetricsCollector]:
    """Instantiate all services, wire the pipeline, return the runnable task."""

    cfg = settings

    # ── Transport ──────────────────────────────────────────────────────────
    transport = LiveKitTransport(
        url=cfg.livekit_url,
        token=token,
        room_name=room_name,
        params=LiveKitParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=cfg.transport.audio_in_sample_rate,
            audio_out_sample_rate=cfg.transport.audio_out_sample_rate,
            audio_in_channels=cfg.transport.audio_in_channels,
            audio_out_channels=cfg.transport.audio_out_channels,
        ),
    )

    # ── VAD processor (emits VADUserStarted/StoppedSpeakingFrame) ────────
    vad_processor = VADProcessor(
        vad_analyzer=SileroVADAnalyzer(
            params=VADParams(
                confidence=cfg.vad.threshold,
                stop_secs=cfg.vad.min_silence_ms / 1000.0,
                start_secs=cfg.vad.min_speech_ms / 1000.0,
            )
        )
    )

    # ── State machine + memory + metrics ──────────────────────────────────
    state_machine = ConversationStateMachine(
        processing_timeout_secs=cfg.state_machine.processing_timeout_secs,
        degraded_retry_delay_secs=cfg.state_machine.degraded_retry_delay_secs,
    )
    memory = SessionMemory(
        system_prompt=cfg.llm.system_prompt,
        max_turns=cfg.llm.context_turns,
        max_context_tokens=cfg.llm.max_context_tokens,
        max_response_tokens=cfg.llm.max_tokens,
    )
    metrics = MetricsCollector(session_id=session_id)

    # ── Barge-in controller ───────────────────────────────────────────────
    barge_in = BargeInController(config=cfg.barge_in)

    # ── Conversation controller ────────────────────────────────────────────
    controller = ConversationController(
        state_machine=state_machine,
        memory=memory,
        transport=transport,
        session_id=session_id,
    )
    state_machine.on_state_change(controller.publish_state)

    # ── STT ───────────────────────────────────────────────────────────────
    stt_service = FasterWhisperSTTService(
        stt_config=cfg.stt,
        smart_turn_config=cfg.smart_turn,
    )
    await stt_service.initialize()  # loads faster-whisper model (downloads on first run)

    # ── LLM (pipecat native OpenAI service) ───────────────────────────────
    llm_context = LLMContext(messages=memory.get_messages())
    llm_service = OpenAILLMService(
        api_key=cfg.openai_api_key,
        model=cfg.llm.model,
        params=OpenAILLMService.InputParams(
            temperature=cfg.llm.temperature,
            top_p=cfg.llm.top_p,
            max_completion_tokens=cfg.llm.max_tokens,
        ),
    )
    context_aggregator = LLMContextAggregatorPair(
        llm_context,
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                start=[TranscriptionUserTurnStartStrategy()],
                stop=[ExternalUserTurnStopStrategy(timeout=0.1)],
            )
        ),
    )

    # ── Text chunker ─────────────────────────────────────────────────────
    chunker = TextChunker(config=cfg.chunker)
    assistant_publisher = AssistantResponsePublisher(
        memory=memory,
        transport=transport,
        llm_context=llm_context,
    )

    # ── TTS ───────────────────────────────────────────────────────────────
    tts_service = PiperTTSService(config=cfg.tts)
    await tts_service.initialize()  # loads Piper voice model and warms synthesis

    # ── Assemble pipeline ─────────────────────────────────────────────────
    pipeline = Pipeline(
        [
            transport.input(),
            vad_processor,
            barge_in,
            stt_service,
            controller,
            metrics,
            context_aggregator.user(),
            llm_service,
            chunker,
            assistant_publisher,
            tts_service,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=True),
        cancel_on_idle_timeout=False,
        idle_timeout_secs=None,
    )

    greeted_participants: set[str] = set()

    async def _queue_greeting(participant: Any) -> None:
        identity = _participant_identity(participant)
        if identity == "agent" or identity in greeted_participants or not cfg.llm.greeting.strip():
            return

        greeted_participants.add(identity)
        log.info("queue_greeting", participant=identity, text=cfg.llm.greeting)
        await asyncio.sleep(0.2)
        await task.queue_frame(TextFrame(text=cfg.llm.greeting), FrameDirection.DOWNSTREAM)

    def _participant_identity(participant: Any) -> str:
        if isinstance(participant, str):
            return participant
        return (
            getattr(participant, "identity", "")
            or getattr(participant, "sid", "")
            or repr(participant)
        )

    @transport.event_handler("on_participant_connected")
    async def _on_participant_connected(
        _transport: LiveKitTransport,
        participant: Any,
    ) -> None:
        identity = _participant_identity(participant)
        log.info("participant_connected", participant=identity)

        async def _delayed_greeting() -> None:
            await asyncio.sleep(2.0)
            await _queue_greeting(identity)

        asyncio.create_task(_delayed_greeting())

    @transport.event_handler("on_data_received")
    async def _on_data_received(
        _transport: LiveKitTransport,
        data: bytes,
        participant: Any,
    ) -> None:
        try:
            message = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        if message.get("type") == "client_ready":
            await _queue_greeting(participant)

    @transport.event_handler("on_participant_disconnected")
    async def _on_participant_disconnected(
        _transport: LiveKitTransport,
        participant: Any,
    ) -> None:
        greeted_participants.discard(_participant_identity(participant))

    return task, state_machine, memory, metrics
