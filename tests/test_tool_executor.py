import pytest

from harness.model_client import ToolCall
from harness.scenario import ToolDef
from harness.tool_executor import ToolMockExecutor
from harness.tool_hooks import clear_hooks, register_hook

LOOKUP_TOOL = ToolDef(
    name="lookup_order",
    description="Look up an order by id.",
    parameters={
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
        "required": ["order_id"],
    },
    responses={'{"order_id": "A100"}': {"status": "shipped"}},
    default_response={"error": "order_not_found"},
)


@pytest.fixture(autouse=True)
def _clear_hooks():
    clear_hooks()
    yield
    clear_hooks()


def _call(name: str, arguments: dict) -> ToolCall:
    return ToolCall(id="call_1", name=name, arguments=arguments, raw_arguments=str(arguments))


def test_unknown_tool_is_hallucinated():
    executor = ToolMockExecutor([LOOKUP_TOOL], scenario_id="s1")
    record = executor.execute(_call("delete_everything", {}))
    assert record.error == "unknown_tool"
    assert record.response is None


def test_invalid_args_fail_schema_validation():
    executor = ToolMockExecutor([LOOKUP_TOOL], scenario_id="s1")
    record = executor.execute(_call("lookup_order", {"wrong_field": 1}))
    assert record.error == "invalid_args"


def test_matching_response_table_entry_returned():
    executor = ToolMockExecutor([LOOKUP_TOOL], scenario_id="s1")
    record = executor.execute(_call("lookup_order", {"order_id": "A100"}))
    assert record.error is None
    assert record.response == {"status": "shipped"}


def test_unmatched_args_fall_back_to_default_response():
    executor = ToolMockExecutor([LOOKUP_TOOL], scenario_id="s1")
    record = executor.execute(_call("lookup_order", {"order_id": "UNKNOWN"}))
    assert record.error is None
    assert record.response == {"error": "order_not_found"}


def test_no_default_response_is_reported():
    tool = LOOKUP_TOOL.model_copy(update={"default_response": None, "responses": {}})
    executor = ToolMockExecutor([tool], scenario_id="s1")
    record = executor.execute(_call("lookup_order", {"order_id": "A100"}))
    assert record.error == "no_mock_response"


def test_stateful_hook_wins_over_response_table():
    register_hook("s1", "lookup_order", lambda args: {"status": "from_hook", "seen": args})
    executor = ToolMockExecutor([LOOKUP_TOOL], scenario_id="s1")
    record = executor.execute(_call("lookup_order", {"order_id": "A100"}))
    assert record.response == {"status": "from_hook", "seen": {"order_id": "A100"}}


def test_hook_is_scoped_to_its_scenario_id():
    register_hook("other_scenario", "lookup_order", lambda args: {"status": "from_hook"})
    executor = ToolMockExecutor([LOOKUP_TOOL], scenario_id="s1")
    record = executor.execute(_call("lookup_order", {"order_id": "A100"}))
    assert record.response == {"status": "shipped"}  # unaffected by the other scenario's hook
