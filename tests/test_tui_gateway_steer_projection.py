from tui_gateway.server import _history_to_messages


def test_history_projection_renders_pending_tool_steer_as_user_message():
    messages = _history_to_messages([
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "function": {"name": "terminal", "arguments": "{}"}}],
            "display_metadata": {"steer_corrections": ["focus on the failure"]},
            "timestamp": 12.0,
        },
    ])

    assert [(message["role"], message.get("text")) for message in messages] == [("user", "focus on the failure")]


def test_history_projection_renders_persisted_tool_steer_as_user_message():
    messages = _history_to_messages([
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "function": {"name": "terminal", "arguments": "{}"}}],
        },
        {
            "role": "tool",
            "content": "command output",
            "tool_call_id": "call-1",
            "display_metadata": {"steer_corrections": ["focus on the failure"]},
            "timestamp": 12.0,
        },
        {"role": "assistant", "content": "Corrected reply"},
    ])

    assert [(message["role"], message.get("text")) for message in messages] == [
        ("tool", None), ("user", "focus on the failure"), ("assistant", "Corrected reply"),
    ]
