from harness.metrics.task_completion import TaskCompletionMetric, infer_resolution
from harness.scenario import ExpectedOutcome, Persona, Scenario, UserSimulation
from harness.transcript import ToolCallRecord, Transcript, Turn


def _scenario(**outcome_kwargs) -> Scenario:
    return Scenario(
        id="s1",
        intent="order_status",
        description="check order status",
        opening_message="hi",
        user_simulation=UserSimulation(
            mode="simulated", persona=Persona(name="Alex", goal="find my order")
        ),
        expected_outcome=ExpectedOutcome(resolution="resolved", **outcome_kwargs),
    )


def _transcript(end_reason, turns=None, messages=None) -> Transcript:
    return Transcript(
        scenario_id="s1",
        end_reason=end_reason,
        turns=turns or [],
        messages=messages or [],
    )


async def test_fully_passing_scenario():
    scenario = _scenario(
        required_tool_calls=["lookup_order"],
        must_mention=["shipped"],
    )
    transcript = _transcript(
        "goal_achieved",
        turns=[
            Turn(
                agent_message="Your order has shipped.",
                tool_calls=[
                    ToolCallRecord(id="c1", name="lookup_order", arguments={"order_id": "A100"})
                ],
            )
        ],
    )

    result = await TaskCompletionMetric().score(transcript, scenario)

    assert result.passed is True
    assert result.score == 1.0
    assert all(result.details.values())


async def test_missing_required_tool_call_fails():
    scenario = _scenario(required_tool_calls=["lookup_order"])
    transcript = _transcript("goal_achieved", turns=[Turn(agent_message="Your order has shipped.")])

    result = await TaskCompletionMetric().score(transcript, scenario)

    assert result.passed is False
    assert result.details["required_tool_calls"] is False


async def test_forbidden_tool_call_fails():
    scenario = _scenario(forbidden_tool_calls=["delete_account"])
    transcript = _transcript(
        "goal_achieved",
        turns=[
            Turn(
                agent_message="Done.",
                tool_calls=[ToolCallRecord(id="c1", name="delete_account", arguments={})],
            )
        ],
    )

    result = await TaskCompletionMetric().score(transcript, scenario)

    assert result.details["forbidden_tool_calls"] is False
    assert result.passed is False


async def test_must_mention_fails_when_absent():
    scenario = _scenario(must_mention=["refund"])
    transcript = _transcript("goal_achieved", turns=[Turn(agent_message="Your order has shipped.")])

    result = await TaskCompletionMetric().score(transcript, scenario)

    assert result.details["must_mention"] is False
    assert result.passed is False


async def test_must_not_mention_fails_when_present():
    scenario = _scenario(must_not_mention=["password"])
    transcript = _transcript("goal_achieved", turns=[Turn(agent_message="Your password is reset.")])

    result = await TaskCompletionMetric().score(transcript, scenario)

    assert result.details["must_not_mention"] is False
    assert result.passed is False


async def test_resolution_mismatch_fails():
    scenario = _scenario()  # expects "resolved"
    transcript = _transcript("max_turns", turns=[Turn(agent_message="still working on it")])

    result = await TaskCompletionMetric().score(transcript, scenario)

    assert result.details["resolution"] is False
    assert result.passed is False


def test_infer_resolution_goal_achieved_is_resolved():
    scenario = _scenario()
    transcript = _transcript("goal_achieved")
    assert infer_resolution(transcript, scenario) == "resolved"


def test_infer_resolution_max_turns_is_none():
    scenario = _scenario()
    transcript = _transcript("max_turns")
    assert infer_resolution(transcript, scenario) is None


def test_infer_resolution_escalated_when_escalation_tool_called():
    scenario = Scenario(
        id="s1",
        intent="order_status",
        description="check order status",
        opening_message="hi",
        user_simulation=UserSimulation(
            mode="simulated", persona=Persona(name="Alex", goal="find my order")
        ),
        expected_outcome=ExpectedOutcome(
            resolution="escalated", required_tool_calls=["escalate_to_human"]
        ),
    )
    transcript = _transcript(
        "gave_up",
        turns=[
            Turn(
                agent_message="Let me get a human to help.",
                tool_calls=[ToolCallRecord(id="c1", name="escalate_to_human", arguments={})],
            )
        ],
    )
    assert infer_resolution(transcript, scenario) == "escalated"


def test_infer_resolution_refused_when_no_tools_called():
    scenario = Scenario(
        id="s1",
        intent="order_status",
        description="check order status",
        opening_message="hi",
        user_simulation=UserSimulation(
            mode="simulated", persona=Persona(name="Alex", goal="find my order")
        ),
        expected_outcome=ExpectedOutcome(resolution="refused"),
    )
    transcript = _transcript("gave_up", turns=[Turn(agent_message="I can't help with that.")])
    assert infer_resolution(transcript, scenario) == "refused"
