from harness.metrics.efficiency import EfficiencyMetric, ModelPricing, compute, load_pricing
from harness.scenario import ExpectedOutcome, Persona, Scenario, UserSimulation
from harness.transcript import Transcript, Turn

PRICING = {
    "gpt-4o-mini": ModelPricing(prompt_per_1k=0.00015, completion_per_1k=0.0006),
    "free-model": ModelPricing(prompt_per_1k=0.0, completion_per_1k=0.0),
}


def _scenario() -> Scenario:
    return Scenario(
        id="s1",
        intent="order_status",
        description="check order status",
        opening_message="hi",
        user_simulation=UserSimulation(
            mode="simulated", persona=Persona(name="Alex", goal="find my order")
        ),
        expected_outcome=ExpectedOutcome(resolution="resolved"),
    )


def _transcript(turns) -> Transcript:
    return Transcript(scenario_id="s1", end_reason="goal_achieved", turns=turns)


def test_compute_sums_tokens_and_cost_across_turns():
    turns = [
        Turn(agent_message="a", model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=1000),
        Turn(agent_message="b", model="gpt-4o-mini", prompt_tokens=500, completion_tokens=500),
    ]
    detail = compute(_transcript(turns), PRICING)

    assert detail.turns == 2
    assert detail.prompt_tokens == 1500
    assert detail.completion_tokens == 1500
    # (1.5 * 0.00015) + (1.5 * 0.0006)
    assert round(detail.cost_usd, 6) == round(1.5 * 0.00015 + 1.5 * 0.0006, 6)


def test_compute_skips_unpriced_model():
    turns = [
        Turn(agent_message="a", model="unknown-model", prompt_tokens=100, completion_tokens=100)
    ]
    detail = compute(_transcript(turns), PRICING)
    assert detail.cost_usd == 0.0


def test_compute_skips_turn_with_no_model():
    turns = [Turn(agent_message="a", prompt_tokens=100, completion_tokens=100)]
    detail = compute(_transcript(turns), PRICING)
    assert detail.cost_usd == 0.0


def test_free_model_costs_nothing():
    turns = [
        Turn(agent_message="a", model="free-model", prompt_tokens=1000, completion_tokens=1000)
    ]
    detail = compute(_transcript(turns), PRICING)
    assert detail.cost_usd == 0.0


def test_score_at_target_turns_is_one():
    turns = [Turn(agent_message=f"turn {i}") for i in range(6)]
    result = EfficiencyMetric(PRICING, target_turns=6).score(_transcript(turns), _scenario())
    assert result.score == 1.0
    assert result.passed is None


def test_score_below_target_turns_is_capped_at_one():
    turns = [Turn(agent_message="only turn")]
    result = EfficiencyMetric(PRICING, target_turns=6).score(_transcript(turns), _scenario())
    assert result.score == 1.0


def test_score_above_target_turns_is_proportionally_lower():
    turns = [Turn(agent_message=f"turn {i}") for i in range(12)]
    result = EfficiencyMetric(PRICING, target_turns=6).score(_transcript(turns), _scenario())
    assert result.score == 0.5


def test_load_pricing_reads_yaml(tmp_path):
    path = tmp_path / "pricing.yaml"
    path.write_text(
        "gpt-4o-mini:\n  prompt_per_1k: 0.00015\n  completion_per_1k: 0.0006\n",
        encoding="utf-8",
    )
    pricing = load_pricing(path)
    assert pricing["gpt-4o-mini"].prompt_per_1k == 0.00015


def test_load_pricing_reads_committed_config():
    pricing = load_pricing("config/model_pricing.yaml")
    assert "gpt-4o-mini" in pricing
    assert "ollama/llama3.1" in pricing
