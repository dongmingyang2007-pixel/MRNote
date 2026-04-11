"""Tests for real-time voice features."""
import asyncio
import base64
import types

import pytest

from app.core.config import Settings
import app.services.orchestrator as orchestrator_service
from app.services.asr_client import RealtimeTranscriptionBridge, transcribe_audio_realtime
from app.services.context_loader import (
    build_system_prompt,
    extract_personality,
)
from app.services.composed_realtime import split_text_for_realtime_tts
from app.services.dashscope_client import UpstreamServiceError
from app.services.realtime_bridge import RealtimeSession, SessionState, register_session, unregister_session
from app.services.voice_response_limits import (
    VOICE_RESPONSE_INSTRUCTION_MARKER,
    append_voice_response_instruction,
    clamp_voice_response_text,
    split_voice_response_sentences,
)


def test_realtime_settings_defaults():
    s = Settings(
        database_url="postgresql+psycopg://x:x@localhost/test",
        jwt_secret="test-secret-that-is-long-enough-32chars",
    )
    assert s.realtime_interrupt_threshold_ms == 500
    assert s.realtime_idle_timeout_seconds == 60
    assert s.realtime_close_timeout_seconds == 120
    assert s.realtime_max_session_seconds == 1800
    assert s.realtime_max_concurrent_sessions == 50
    assert s.realtime_context_history_turns == 10
    assert s.realtime_rag_refresh_turns == 5
    assert s.realtime_reconnect_max_attempts == 3
    assert s.voice_reply_max_sentences == 2
    assert s.voice_reply_soft_char_limit == 60
    assert s.voice_reply_hard_char_limit == 90


def test_memory_triage_settings_defaults():
    s = Settings(
        database_url="postgresql+psycopg://x:x@localhost/test",
        jwt_secret="test-secret-that-is-long-enough-32chars",
    )
    assert s.memory_triage_model == "qwen-turbo"
    assert s.memory_triage_similarity_low == 0.70
    assert s.memory_triage_similarity_high == 0.90


def test_thinking_classifier_settings_defaults():
    s = Settings(
        database_url="postgresql+psycopg://x:x@localhost/test",
        jwt_secret="test-secret-that-is-long-enough-32chars",
    )
    assert s.thinking_classifier_model == "qwen3.5-flash"
    assert s.thinking_classifier_min_confidence == 0.65


def test_extract_personality_from_description():
    assert extract_personality("[personality:你是一个温柔的助手]") == "你是一个温柔的助手"


def test_extract_personality_fallback():
    assert extract_personality("Just a project") == "Just a project"


def test_extract_personality_none():
    assert extract_personality(None) == ""


def test_build_system_prompt_minimal():
    prompt = build_system_prompt(personality="你是助手", memories=[], knowledge_chunks=[])
    assert "你是助手" in prompt


def test_build_system_prompt_with_memories():
    prompt = build_system_prompt(
        personality="你是助手",
        memories=["用户喜欢跑步", "用户住在北京"],
        knowledge_chunks=[],
    )
    assert "用户喜欢跑步" in prompt
    assert "用户住在北京" in prompt


def test_build_system_prompt_with_knowledge():
    prompt = build_system_prompt(
        personality="你是助手",
        memories=[],
        knowledge_chunks=["降噪技术文档片段"],
    )
    assert "降噪技术文档片段" in prompt


def test_split_text_for_realtime_tts_splits_chinese_sentences_without_spaces():
    assert split_text_for_realtime_tts("你好。请看这里！还有一个问题？") == [
        "你好。",
        "请看这里！",
        "还有一个问题？",
    ]


def test_split_text_for_realtime_tts_keeps_decimal_or_inline_periods_inside_segment():
    assert split_text_for_realtime_tts("Version 2.1 is stable. Next step starts now.") == [
        "Version 2.1 is stable.",
        "Next step starts now.",
    ]


def test_append_voice_response_instruction_is_idempotent():
    prompt = "你是一个简洁的助手。"
    updated = append_voice_response_instruction(prompt)

    assert VOICE_RESPONSE_INSTRUCTION_MARKER in updated
    assert append_voice_response_instruction(updated) == updated


def test_clamp_voice_response_text_limits_sentence_count():
    text = "第一句先回答。第二句补充一点。第三句不应该再播了。"

    assert clamp_voice_response_text(
        text,
        max_sentences=2,
        soft_char_limit=30,
        hard_char_limit=40,
    ) == "第一句先回答。第二句补充一点。"


def test_clamp_voice_response_text_trims_long_single_sentence_cleanly():
    text = "这是一个特别长的单句，其中包含很多补充说明，还会继续延伸到不适合语音播报的长度"

    clamped = clamp_voice_response_text(
        text,
        max_sentences=2,
        soft_char_limit=18,
        hard_char_limit=24,
    )

    assert len(clamped) <= 25
    assert clamped.endswith("。")
    assert "不适合语音播报的长度" not in clamped


def test_split_voice_response_sentences_respects_english_periods_and_decimals():
    assert split_voice_response_sentences(
        "Version 2.1 is stable. Next step starts now. Final check passes."
    ) == [
        "Version 2.1 is stable.",
        "Next step starts now.",
        "Final check passes.",
    ]


def test_clamp_voice_response_text_limits_english_sentences_with_spacing():
    assert clamp_voice_response_text(
        "First sentence! Second sentence? Third sentence.",
        max_sentences=2,
        soft_char_limit=80,
        hard_char_limit=90,
    ) == "First sentence! Second sentence?"


def test_clamp_voice_response_text_preserves_terminal_quote_when_truncated():
    assert clamp_voice_response_text(
        "“好的。”第二句补充说明。",
        max_sentences=1,
        soft_char_limit=20,
        hard_char_limit=30,
    ) == "“好的。”"


def test_build_system_prompt_with_recent_messages():
    prompt = build_system_prompt(
        personality="你是助手",
        memories=[],
        knowledge_chunks=[],
        recent_messages=[
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，请说"},
        ],
    )
    assert "最近对话历史" in prompt
    assert "用户: 你好" in prompt
    assert "助手: 你好，请说" in prompt


def test_orchestrate_synthetic_realtime_turn_from_text_clamps_voice_output(monkeypatch):
    captured: dict[str, object] = {}

    def fake_resolve_pipeline_model_id(_db, *, project_id: str, model_type: str) -> str:
        assert project_id == "project-1"
        assert model_type == "llm"
        return "qwen3.5-plus"

    async def fake_build_and_call_llm(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_message: str,
        recent_messages: list[dict[str, str]],
        llm_model_id: str,
        **kwargs,
    ) -> dict[str, object]:
        captured["workspace_id"] = workspace_id
        captured["project_id"] = project_id
        captured["conversation_id"] = conversation_id
        captured["user_message"] = user_message
        captured["recent_messages"] = list(recent_messages)
        captured["llm_model_id"] = llm_model_id
        captured["voice_response_mode"] = kwargs.get("voice_response_mode")
        return {
            "content": "第一句先回答。第二句补充一点。第三句不应该再播了。",
            "reasoning_content": None,
            "sources": [],
            "retrieval_trace": {},
        }

    monkeypatch.setattr(orchestrator_service, "resolve_pipeline_model_id", fake_resolve_pipeline_model_id)
    monkeypatch.setattr(orchestrator_service, "load_recent_messages", lambda _db, *, conversation_id, limit: [])
    monkeypatch.setattr(orchestrator_service, "_build_and_call_llm", fake_build_and_call_llm)

    result = asyncio.run(
        orchestrator_service.orchestrate_synthetic_realtime_turn_from_text(
            None,
            workspace_id="workspace-1",
            project_id="project-1",
            conversation_id="conversation-1",
            user_text="晚上好",
        )
    )

    assert captured["voice_response_mode"] is True
    assert result["text_input"] == "晚上好"
    assert result["text_response"] == "第一句先回答。第二句补充一点。"


def test_orchestrate_voice_inference_clamps_audio_reply_before_tts(monkeypatch):
    captured: dict[str, object] = {}

    class FakeTransaction:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeQuery:
        def __init__(self, result):
            self._result = result

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return self._result

    class FakeDb:
        def __init__(self):
            self.model_info = types.SimpleNamespace(capabilities=["text"])

        def query(self, _model):
            return FakeQuery(self.model_info)

        def begin_nested(self):
            return FakeTransaction()

    def fake_resolve_pipeline_model_id(_db, *, project_id: str, model_type: str) -> str:
        assert project_id == "project-1"
        if model_type == "llm":
            return "qwen3.5-plus"
        raise AssertionError(f"unexpected model_type {model_type}")

    async def fake_build_and_call_llm(
        _db,
        *,
        workspace_id: str,
        project_id: str,
        conversation_id: str,
        user_message: str,
        recent_messages: list[dict[str, str]],
        llm_model_id: str,
        **kwargs,
    ) -> dict[str, object]:
        captured["workspace_id"] = workspace_id
        captured["project_id"] = project_id
        captured["conversation_id"] = conversation_id
        captured["user_message"] = user_message
        captured["recent_messages"] = list(recent_messages)
        captured["llm_model_id"] = llm_model_id
        captured["voice_response_mode"] = kwargs.get("voice_response_mode")
        return {
            "content": "第一句先回答。第二句补充一点。第三句不应该再播了。",
            "reasoning_content": None,
            "sources": [],
            "retrieval_trace": {},
        }

    async def fake_synthesize_speech_for_project(_db, *, project_id: str, text: str) -> bytes:
        captured["tts_project_id"] = project_id
        captured["tts_text"] = text
        return b"\x01\x02"

    monkeypatch.setattr(orchestrator_service, "resolve_pipeline_model_id", fake_resolve_pipeline_model_id)
    monkeypatch.setattr(orchestrator_service, "load_recent_messages", lambda _db, *, conversation_id, limit: [])
    monkeypatch.setattr(orchestrator_service, "_load_model_capabilities", lambda _db, *, model_id: {"text"})
    monkeypatch.setattr(orchestrator_service, "_build_and_call_llm", fake_build_and_call_llm)
    monkeypatch.setattr(orchestrator_service, "synthesize_speech_for_project", fake_synthesize_speech_for_project)

    result = asyncio.run(
        orchestrator_service.orchestrate_voice_inference(
            FakeDb(),
            workspace_id="workspace-1",
            project_id="project-1",
            conversation_id="conversation-1",
            text_input="晚上好",
        )
    )

    assert captured["voice_response_mode"] is True
    assert captured["tts_project_id"] == "project-1"
    assert captured["tts_text"] == "第一句先回答。第二句补充一点。"
    assert result["text_response"] == "第一句先回答。第二句补充一点。"
    assert result["audio_response"] == b"\x01\x02"


def test_session_initial_state():
    session = RealtimeSession(
        workspace_id="ws1",
        project_id="proj1",
        conversation_id="conv1",
        user_id="user1",
    )
    assert session.state == SessionState.CONNECTING
    assert session.turn_count == 0
    assert session.is_ai_speaking is False


def test_session_should_interrupt_short_speech():
    session = RealtimeSession(
        workspace_id="ws1",
        project_id="proj1",
        conversation_id="conv1",
        user_id="user1",
    )
    session._ai_speaking = True
    assert session.should_interrupt(speech_duration_ms=200) is False


def test_session_should_interrupt_long_speech():
    session = RealtimeSession(
        workspace_id="ws1",
        project_id="proj1",
        conversation_id="conv1",
        user_id="user1",
    )
    session._ai_speaking = True
    assert session.should_interrupt(speech_duration_ms=600) is True


def test_session_should_not_interrupt_when_ai_silent():
    session = RealtimeSession(
        workspace_id="ws1",
        project_id="proj1",
        conversation_id="conv1",
        user_id="user1",
    )
    session._ai_speaking = False
    assert session.should_interrupt(speech_duration_ms=600) is False


def test_register_session_blocks_duplicate_user():
    """One user cannot have two concurrent sessions."""
    from app.services.realtime_bridge import _active_sessions

    _active_sessions.clear()

    s1 = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c1", user_id="u1")
    s2 = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c2", user_id="u1")

    assert asyncio.run(register_session("u1", s1)) is True
    assert asyncio.run(register_session("u1", s2)) is False

    asyncio.run(unregister_session("u1"))
    assert asyncio.run(register_session("u1", s2)) is True
    asyncio.run(unregister_session("u1"))
    _active_sessions.clear()


def test_register_session_enforces_global_limit(monkeypatch):
    """Global concurrent session limit is enforced."""
    from app.services.realtime_bridge import _active_sessions

    _active_sessions.clear()

    monkeypatch.setattr("app.services.realtime_bridge.settings.realtime_max_concurrent_sessions", 2)

    s1 = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c1", user_id="u1")
    s2 = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c2", user_id="u2")
    s3 = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c3", user_id="u3")

    assert asyncio.run(register_session("u1", s1)) is True
    assert asyncio.run(register_session("u2", s2)) is True
    assert asyncio.run(register_session("u3", s3)) is False  # limit reached

    asyncio.run(unregister_session("u1"))
    asyncio.run(unregister_session("u2"))
    _active_sessions.clear()


def test_session_get_turn_texts():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._current_transcript = "你好"
    session._current_response_text = "你好，有什么可以帮你的？"

    user_text, ai_text = session.get_turn_texts()
    assert user_text == "你好"
    assert ai_text == "你好，有什么可以帮你的？"
    # Should be cleared after retrieval
    assert session._current_transcript == ""
    assert session._current_response_text == ""


def test_session_maps_audio_transcript_delta_to_response_text():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")

    outgoing = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.audio_transcript.delta",
                "delta": "你好",
            }
        )
    )

    assert outgoing == [{"type": "response.text", "text": "你好"}]
    assert session._current_response_text == "你好"


def test_session_deduplicates_audio_transcript_delta_when_text_delta_already_arrived():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")

    first = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": "你好",
            }
        )
    )
    second = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.audio_transcript.delta",
                "delta": "你好",
            }
        )
    )

    assert first == [{"type": "response.text", "text": "你好"}]
    assert second == []
    assert session._current_response_text == "你好"


def test_session_switches_to_text_stream_without_repeating_audio_transcript_prefix():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")

    first = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.audio_transcript.delta",
                "delta": "你",
            }
        )
    )
    second = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": "你好",
            }
        )
    )

    assert first == [{"type": "response.text", "text": "你"}]
    assert second == [{"type": "response.text", "text": "好"}]
    assert session._current_response_text == "你好"


def test_session_replaces_visible_text_when_audio_and_text_streams_diverge():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")

    first = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.audio_transcript.delta",
                "delta": "你好呀",
            }
        )
    )
    second = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": "你好，今天",
            }
        )
    )

    assert first == [{"type": "response.text", "text": "你好呀"}]
    assert second == [{"type": "response.text", "text": "你好，今天", "replace": True}]
    assert session._current_response_text == "你好，今天"


def test_session_accumulates_partial_user_transcripts():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")

    first = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "delta": "你",
            }
        )
    )
    second = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "delta": "好",
            }
        )
    )

    assert first == [{"type": "transcript.partial", "text": "你"}]
    assert second == [{"type": "transcript.partial", "text": "你好"}]


def test_session_maps_text_and_stash_partial_user_transcripts():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")

    first = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "conversation.item.input_audio_transcription.text",
                "text": "今",
                "stash": "天",
            }
        )
    )
    second = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "conversation.item.input_audio_transcription.text",
                "text": "今天",
                "stash": "天气",
            }
        )
    )

    assert first == [{"type": "transcript.partial", "text": "今天"}]
    assert second == [{"type": "transcript.partial", "text": "今天天气"}]


def test_session_backfills_audio_transcript_done_when_delta_was_missing():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")

    outgoing = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.audio_transcript.done",
                "transcript": "你好，世界",
            }
        )
    )

    assert outgoing == [{"type": "response.text", "text": "你好，世界"}]
    assert session._current_response_text == "你好，世界"


def test_session_audio_transcript_done_only_backfills_missing_suffix_after_text_delta():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")

    asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": "你好",
            }
        )
    )
    outgoing = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.audio_transcript.done",
                "transcript": "你好。",
            }
        )
    )

    assert outgoing == [{"type": "response.text", "text": "。"}]
    assert session._current_response_text == "你好。"


def test_session_cancels_over_limit_voice_stream_and_preserves_clamped_text():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()

    first = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": "First sentence! ",
            }
        )
    )
    second = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": "Second sentence?",
            }
        )
    )
    third = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": " Third sentence.",
            }
        )
    )
    ignored_audio = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.audio.delta",
                "delta": base64.b64encode(b"ignored").decode("utf-8"),
            }
        )
    )
    done = asyncio.run(session.handle_upstream_event({"type": "response.done"}))

    assert first == [{"type": "response.text", "text": "First sentence!"}]
    assert second == [{"type": "response.text", "text": " Second sentence?"}]
    assert third == []
    assert ignored_audio == []
    assert done == [{"type": "response.done"}]
    assert session._current_response_text == "First sentence! Second sentence?"
    assert [json.loads(message) for message in session._upstream_ws.sent_messages] == [
        {"type": "response.cancel"},
    ]

    user_text, ai_text = session.get_turn_texts()
    assert user_text == ""
    assert ai_text == "First sentence! Second sentence?"


class _DummyUpstream:
    def __init__(self, incoming_messages: list[str] | None = None) -> None:
        self.sent_messages: list[str] = []
        self._incoming_messages = list(incoming_messages or [])

    async def send(self, message: str) -> None:
        self.sent_messages.append(message)

    async def recv(self) -> str:
        if not self._incoming_messages:
            raise RuntimeError("No queued upstream messages")
        return self._incoming_messages.pop(0)

    async def close(self) -> None:
        return None


class _DummyAsyncConnect:
    def __init__(self, ws) -> None:
        self.ws = ws

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _DummyRealtimeAsrSocket:
    def __init__(self, incoming_messages: list[str]) -> None:
        self.sent_messages: list[str] = []
        self._incoming_messages = list(incoming_messages)

    async def send(self, message: str) -> None:
        self.sent_messages.append(message)

    async def recv(self) -> str:
        if not self._incoming_messages:
            raise RuntimeError("No queued realtime ASR messages")
        return self._incoming_messages.pop(0)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self._incoming_messages:
            raise StopAsyncIteration
        return self._incoming_messages.pop(0)


def test_session_update_confirmation_is_resolved_by_listener():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()

    async def scenario() -> None:
        task = asyncio.create_task(session.send_session_update("你是助手"))
        await asyncio.sleep(0)
        assert session._upstream_ws.sent_messages
        await session.handle_upstream_event({"type": "session.updated"})
        await task

    asyncio.run(scenario())
    assert session.state == SessionState.READY


def test_initial_session_update_reads_confirmation_without_listener():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream([
        '{"type":"session.updated"}',
    ])

    asyncio.run(session.send_initial_session_update("你是助手"))

    assert session.state == SessionState.READY
    assert session._upstream_ws.sent_messages


def test_initial_session_update_surfaces_upstream_error():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream([
        '{"type":"error","error":{"message":"boom"}}',
    ])

    with pytest.raises(UpstreamServiceError, match="DashScope session error"):
        asyncio.run(session.send_initial_session_update("你是助手"))


def test_realtime_session_update_payload_requires_explicit_response_creation():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")

    payload = session._build_session_update_payload("你是助手")

    assert payload["session"]["turn_detection"]["create_response"] is False


def test_request_response_sends_response_create_message():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()

    asyncio.run(session.request_response())

    sent = [json.loads(message) for message in session._upstream_ws.sent_messages]
    assert sent == [{"type": "response.create"}]


def test_relay_image_to_upstream_sends_input_image_append_after_audio_started():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()
    session._has_sent_input_audio = True

    asyncio.run(session.relay_image_to_upstream(b"\xff\xd8\xff\xdbframe"))

    sent = [json.loads(message) for message in session._upstream_ws.sent_messages]
    assert sent == [
        {
            "type": "input_image_buffer.append",
            "image": base64.b64encode(b"\xff\xd8\xff\xdbframe").decode("utf-8"),
        }
    ]


def test_first_audio_chunk_flushes_latest_pending_image_frame():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()

    asyncio.run(session.relay_image_to_upstream(b"\xff\xd8\xfffirst"))
    asyncio.run(session.relay_image_to_upstream(b"\xff\xd8\xfflatest"))
    asyncio.run(session.relay_audio_to_upstream(b"\x01\x02\x03\x04"))

    sent = [json.loads(message) for message in session._upstream_ws.sent_messages]
    assert sent == [
        {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(b"\x01\x02\x03\x04").decode("utf-8"),
        },
        {
            "type": "input_image_buffer.append",
            "image": base64.b64encode(b"\xff\xd8\xfflatest").decode("utf-8"),
        },
    ]


def test_transcribe_audio_realtime_encodes_each_raw_chunk_independently(monkeypatch):
    monkeypatch.setattr("app.services.asr_client.settings.dashscope_api_key", "test-key")
    ws = _DummyRealtimeAsrSocket([
        '{"type":"session.updated"}',
        '{"type":"conversation.item.input_audio_transcription.completed","transcript":"你好"}',
        '{"type":"session.finished"}',
    ])
    monkeypatch.setattr(
        "app.services.asr_client.websockets.connect",
        lambda *args, **kwargs: _DummyAsyncConnect(ws),
    )

    audio_bytes = bytes(range(256)) * 50
    result = asyncio.run(transcribe_audio_realtime(audio_bytes))

    assert result == "你好"
    sent_messages = [json.loads(message) for message in ws.sent_messages]
    append_chunks = [
        message["audio"]
        for message in sent_messages
        if message.get("type") == "input_audio_buffer.append"
    ]
    expected_chunks = [
        base64.b64encode(audio_bytes[i : i + 8192]).decode("utf-8")
        for i in range(0, len(audio_bytes), 8192)
    ]
    assert append_chunks == expected_chunks
    assert sent_messages[-2] == {"type": "input_audio_buffer.commit"}
    assert sent_messages[-1] == {"type": "session.finish"}


def test_transcribe_audio_realtime_returns_empty_text_for_empty_audio_stream(monkeypatch):
    monkeypatch.setattr("app.services.asr_client.settings.dashscope_api_key", "test-key")
    ws = _DummyRealtimeAsrSocket([
        '{"type":"session.updated"}',
        '{"type":"error","error":{"message":"Error committing input audio buffer, maybe no invalid audio stream."}}',
    ])
    monkeypatch.setattr(
        "app.services.asr_client.websockets.connect",
        lambda *args, **kwargs: _DummyAsyncConnect(ws),
    )

    result = asyncio.run(transcribe_audio_realtime(b"\x00\x00" * 32))

    assert result == ""


def test_realtime_transcription_bridge_maps_text_and_stash_to_partial_events():
    bridge = RealtimeTranscriptionBridge()
    bridge._ws = _DummyRealtimeAsrSocket([
        '{"type":"input_audio_buffer.speech_started"}',
        '{"type":"conversation.item.input_audio_transcription.text","text":"今","stash":"天"}',
        '{"type":"conversation.item.input_audio_transcription.text","text":"今天","stash":"天气"}',
        '{"type":"conversation.item.input_audio_transcription.completed","transcript":"今天天气"}',
        '{"type":"session.finished"}',
    ])

    async def scenario():
        listener = asyncio.create_task(bridge._listen())
        events = [
            await bridge.next_event(),
            await bridge.next_event(),
            await bridge.next_event(),
            await bridge.next_event(),
        ]
        await listener
        return events

    events = asyncio.run(scenario())

    assert events == [
        {"type": "transcript.partial", "text": "今天"},
        {"type": "transcript.partial", "text": "今天天气"},
        {"type": "transcript.final", "text": "今天天气"},
        {"type": "session.closed", "text": ""},
    ]


def test_realtime_session_accumulates_multiple_completed_transcripts() -> None:
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")

    first = asyncio.run(
        session.handle_upstream_event(
            {"type": "conversation.item.input_audio_transcription.completed", "transcript": "第一句。"}
        )
    )
    second = asyncio.run(
        session.handle_upstream_event(
            {"type": "conversation.item.input_audio_transcription.completed", "transcript": "第二句。"}
        )
    )

    assert first == [{"type": "transcript.final", "text": "第一句。"}]
    assert second == [{"type": "transcript.final", "text": "第一句。第二句。"}]
    user_text, ai_text = session.get_turn_texts()
    assert user_text == "第一句。第二句。"
    assert ai_text == ""


def test_realtime_session_speech_stopped_arms_response_refresh() -> None:
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._awaiting_transcript_response = False
    session._response_request_started_for_current_input = True
    session._latest_transcript_completion = "旧转写"

    outgoing = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "input_audio_buffer.speech_stopped",
            }
        )
    )

    assert outgoing == []
    assert session._awaiting_transcript_response is True
    assert session._response_request_started_for_current_input is False
    assert session._latest_transcript_completion == ""


def test_ai_output_activity_refreshes_idle_timer():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._last_activity = 0

    asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": "你好",
            }
        )
    )

    assert session._last_activity > 0


import json


def test_client_input_interrupt_while_ai_speaking_returns_ack():
    """input.interrupt during ai_speaking triggers cancel and returns interrupt.ack."""
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()
    session._ai_speaking = True

    replies = asyncio.run(session.handle_client_message("input.interrupt", {"type": "input.interrupt"}))

    assert replies == [{"type": "interrupt.ack"}]
    assert session._ai_speaking is False
    sent = [json.loads(m) for m in session._upstream_ws.sent_messages]
    assert any(m.get("type") == "response.cancel" for m in sent)


def test_client_input_interrupt_while_response_is_pending_returns_ack():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()
    session._response_in_flight = True

    replies = asyncio.run(session.handle_client_message("input.interrupt", {"type": "input.interrupt"}))

    assert replies == [{"type": "interrupt.ack"}]
    assert session._response_in_flight is False
    sent = [json.loads(m) for m in session._upstream_ws.sent_messages]
    assert any(m.get("type") == "response.cancel" for m in sent)


def test_client_input_interrupt_when_ai_silent_is_noop():
    """input.interrupt when AI is not speaking is a no-op (no interrupt.ack returned)."""
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()
    session._ai_speaking = False

    replies = asyncio.run(session.handle_client_message("input.interrupt", {"type": "input.interrupt"}))

    assert replies == []
    assert session._upstream_ws.sent_messages == []


def test_client_interrupt_swallows_stale_response_done_and_output():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()
    session._ai_speaking = True
    session._current_transcript = "第一句"
    session._current_response_text = "旧回答"

    replies = asyncio.run(session.handle_client_message("input.interrupt", {"type": "input.interrupt"}))
    leaked_text = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": "这段不该继续出现",
            }
        )
    )
    stale_done = asyncio.run(session.handle_upstream_event({"type": "response.done"}))

    assert replies == [{"type": "interrupt.ack"}]
    assert leaked_text == []
    assert stale_done == []
    assert session.consume_response_done_finalization() is False
    assert session.turn_count == 0
    user_text, ai_text = session.get_turn_texts()
    assert user_text == ""
    assert ai_text == ""


def test_new_response_output_clears_interrupt_done_guard():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()
    session._ai_speaking = True

    asyncio.run(session.handle_client_message("input.interrupt", {"type": "input.interrupt"}))

    session._reset_response_output_block()
    first = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": "新的回答",
            }
        )
    )
    done = asyncio.run(session.handle_upstream_event({"type": "response.done"}))

    assert first == [{"type": "response.text", "text": "新的回答"}]
    assert done == [{"type": "response.done"}]
    assert session.consume_response_done_finalization() is True


def test_request_response_is_guarded_while_response_in_flight():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    upstream = _DummyUpstream()
    session._upstream_ws = upstream
    session._speech_start_time = 123.0

    asyncio.run(session.request_response())
    asyncio.run(session.request_response())

    sent = [json.loads(message) for message in upstream.sent_messages]
    assert sent == [{"type": "response.create"}]
    assert session._speech_start_time is None


def test_text_only_response_marks_ai_speaking_for_interrupts():
    session = RealtimeSession(workspace_id="ws", project_id="p", conversation_id="c", user_id="u")
    session._upstream_ws = _DummyUpstream()

    first = asyncio.run(
        session.handle_upstream_event(
            {
                "type": "response.text.delta",
                "delta": "你好",
            }
        )
    )
    assert session.is_ai_speaking is True
    replies = asyncio.run(session.handle_client_message("input.interrupt", {"type": "input.interrupt"}))

    assert first == [{"type": "response.text", "text": "你好"}]
    assert session.is_ai_speaking is False
    assert replies == [{"type": "interrupt.ack"}]


def test_triage_memory_parses_merge_response(monkeypatch):
    """triage_memory correctly parses a merge decision from LLM."""
    from app.tasks.worker_tasks import triage_memory

    mock_response = json.dumps({
        "action": "merge",
        "target_memory_id": "mem-123",
        "merged_content": "用户是前端工程师，使用Vue和React",
        "reason": "补充了技术栈细节",
    })

    async def mock_chat(*a, **kw):
        return mock_response

    monkeypatch.setattr("app.services.dashscope_client.chat_completion", mock_chat)

    candidates = [
        {"memory_id": "mem-123", "content": "用户是前端工程师", "category": "工作.职业", "score": 0.82},
    ]
    result = asyncio.run(triage_memory("用户是前端工程师，使用Vue和React", candidates))
    assert result["action"] == "merge"
    assert result["target_memory_id"] == "mem-123"
    assert "Vue" in result["merged_content"]


def test_triage_memory_fallback_on_bad_json(monkeypatch):
    """triage_memory returns create fallback when LLM returns unparseable response."""
    from app.tasks.worker_tasks import triage_memory

    async def mock_chat(*a, **kw):
        return "I don't understand"

    monkeypatch.setattr("app.services.dashscope_client.chat_completion", mock_chat)

    candidates = [
        {"memory_id": "mem-456", "content": "用户住在北京", "category": "生活.住址", "score": 0.75},
    ]
    result = asyncio.run(triage_memory("用户搬到了上海", candidates))
    assert result["action"] == "create"


def test_triage_memory_handles_markdown_wrapped_json(monkeypatch):
    """triage_memory extracts JSON from markdown code blocks."""
    from app.tasks.worker_tasks import triage_memory

    mock_response = '```json\n{"action": "discard", "target_memory_id": null, "merged_content": null, "reason": "重复"}\n```'

    async def mock_chat(*a, **kw):
        return mock_response

    monkeypatch.setattr("app.services.dashscope_client.chat_completion", mock_chat)

    candidates = [
        {"memory_id": "mem-789", "content": "用户喜欢咖啡", "category": "生活.饮食", "score": 0.88},
    ]
    result = asyncio.run(triage_memory("用户爱喝咖啡", candidates))
    assert result["action"] == "discard"


def test_triage_integration_discard_skips_memory_creation(monkeypatch):
    """When triage returns 'discard', no new memory is created."""
    import json as _json

    extraction_response = _json.dumps([{"fact": "用户爱喝咖啡", "category": "饮食", "importance": 0.8}])
    call_count = {"chat": 0}

    async def mock_chat(messages, **kwargs):
        call_count["chat"] += 1
        if call_count["chat"] == 1:
            return extraction_response
        return _json.dumps({"action": "discard", "target_memory_id": None, "merged_content": None, "reason": "重复"})

    monkeypatch.setattr("app.services.dashscope_client.chat_completion", mock_chat)

    async def mock_embed(text, model=None):
        return [0.1] * 1024

    monkeypatch.setattr("app.services.dashscope_client.create_embedding", mock_embed)

    async def mock_dedup(db, *, workspace_id, project_id, text, threshold):
        return None, [0.1] * 1024

    monkeypatch.setattr("app.services.embedding.find_duplicate_memory_with_vector", mock_dedup)

    async def mock_related(db, *, workspace_id, project_id, query_vector, low, high, limit=3):
        return [{"memory_id": "existing-mem", "content": "用户喜欢咖啡", "category": "饮食", "score": 0.85}]

    monkeypatch.setattr("app.services.embedding.find_related_memories", mock_related)

    async def mock_embed_store(db, **kwargs):
        return "emb-id"

    monkeypatch.setattr("app.services.embedding.embed_and_store", mock_embed_store)

    assert call_count["chat"] == 0


def test_triage_integration_append_sets_parent(monkeypatch):
    """When triage returns 'append', verify parent_memory_id is set."""
    import json as _json

    call_count = {"chat": 0}

    async def mock_chat(messages, **kwargs):
        call_count["chat"] += 1
        if call_count["chat"] == 1:
            return _json.dumps([{"fact": "用户每天早上喝美式", "category": "饮食.习惯", "importance": 0.75}])
        return _json.dumps({"action": "append", "target_memory_id": "parent-mem", "merged_content": None, "reason": "细节补充"})

    monkeypatch.setattr("app.services.dashscope_client.chat_completion", mock_chat)

    async def mock_embed(text, model=None):
        return [0.1] * 1024

    monkeypatch.setattr("app.services.dashscope_client.create_embedding", mock_embed)

    assert call_count["chat"] == 0
