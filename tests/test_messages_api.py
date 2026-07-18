"""Anthropic Messages API ↔ ChatRequest conversion."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

# auth.py validates admin config at import time
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.routers.messages import (
    chat_response_to_messages,
    messages_body_to_chat_request,
)


def test_messages_basic_system_and_user():
    req = messages_body_to_chat_request(
        {
            "model": "claude-opus-4-6",
            "max_tokens": 256,
            "system": "Be brief.",
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    assert req.model == "claude-opus-4-6"
    assert req.max_tokens == 256
    assert req.messages[0].role == "system"
    assert req.messages[0].content == "Be brief."
    assert req.messages[1].role == "user"
    assert req.messages[1].content == "hi"


def test_messages_tools_and_tool_result():
    req = messages_body_to_chat_request(
        {
            "model": "claude-sonnet-4-6",
            "max_tokens": 512,
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Weather",
                    "input_schema": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                }
            ],
            "tool_choice": {"type": "auto"},
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "checking"},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "get_weather",
                            "input": {"city": "HN"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "30C",
                        }
                    ],
                },
            ],
        }
    )
    assert req.tools and req.tools[0].function.name == "get_weather"
    assert req.tool_choice == "auto"
    assistant = next(m for m in req.messages if m.role == "assistant")
    assert assistant.tool_calls and assistant.tool_calls[0].id == "toolu_1"
    assert '"city": "HN"' in assistant.tool_calls[0].function.arguments or '"city":"HN"' in (
        assistant.tool_calls[0].function.arguments or ""
    )
    tool = next(m for m in req.messages if m.role == "tool")
    assert tool.tool_call_id == "toolu_1"
    assert tool.content == "30C"


def test_messages_image_base64():
    req = messages_body_to_chat_request(
        {
            "model": "claude-sonnet-4-6",
            "max_tokens": 100,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this?"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "abc123",
                            },
                        },
                    ],
                }
            ],
        }
    )
    user = req.messages[-1]
    assert isinstance(user.content, list)
    assert any(getattr(p, "type", None) == "image_url" for p in user.content)


def test_chat_response_to_messages_text_and_tool():
    chat = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content="ok",
                    tool_calls=[
                        SimpleNamespace(
                            id="toolu_x",
                            function=SimpleNamespace(
                                name="ping",
                                arguments='{"n":1}',
                            ),
                        )
                    ],
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )
    out = chat_response_to_messages(chat, "claude-opus-4-6")
    assert out["type"] == "message"
    assert out["model"] == "claude-opus-4-6"
    assert out["stop_reason"] == "tool_use"
    assert out["usage"]["input_tokens"] == 10
    assert out["content"][0]["type"] == "text"
    assert out["content"][1]["type"] == "tool_use"
    assert out["content"][1]["input"] == {"n": 1}
