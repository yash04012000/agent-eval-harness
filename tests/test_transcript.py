from harness.transcript import ToolCallRecord, Transcript, Turn, all_tool_calls, final_message


def _transcript() -> Transcript:
    return Transcript(
        scenario_id="s1",
        end_reason="goal_achieved",
        turns=[
            Turn(
                agent_message="looking it up",
                tool_calls=[
                    ToolCallRecord(id="c1", name="lookup_order", arguments={"order_id": "A100"})
                ],
            ),
            Turn(agent_message="your order has shipped", tool_calls=[]),
        ],
    )


def test_all_tool_calls_flattens_across_turns():
    calls = all_tool_calls(_transcript())
    assert [c.name for c in calls] == ["lookup_order"]


def test_final_message_is_the_last_turns_message():
    assert final_message(_transcript()) == "your order has shipped"


def test_final_message_empty_when_no_turns():
    empty = Transcript(scenario_id="s1", end_reason="max_turns", turns=[])
    assert final_message(empty) == ""
