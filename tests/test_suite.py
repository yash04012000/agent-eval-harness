from pathlib import Path

from harness.suite import load_suite

FIXTURE_DIR = Path(__file__).parent.parent / "suites"


def test_load_suite_resolves_relative_scenario_paths(tmp_path):
    scenario_yaml = tmp_path / "s1.yaml"
    scenario_yaml.write_text(
        (FIXTURE_DIR / "_schema_smoke.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    manifest_yaml = tmp_path / "manifest.yaml"
    manifest_yaml.write_text(
        "suite: demo\nscenarios:\n  - s1.yaml\nconcurrency: 2\ntoken_budget: 1000\n"
        "simulator_model: fake-sim\njudge_model: fake-judge\n",
        encoding="utf-8",
    )

    suite = load_suite(manifest_yaml)

    assert suite.manifest.suite == "demo"
    assert suite.manifest.concurrency == 2
    assert suite.manifest.token_budget == 1000
    assert suite.manifest.simulator_model == "fake-sim"
    assert suite.manifest.judge_model == "fake-judge"
    assert len(suite.scenarios) == 1
    assert suite.scenarios[0].id == "schema_smoke"


def test_load_suite_defaults(tmp_path):
    manifest_yaml = tmp_path / "manifest.yaml"
    manifest_yaml.write_text("suite: demo\nscenarios: []\n", encoding="utf-8")

    suite = load_suite(manifest_yaml)

    assert suite.manifest.concurrency == 4
    assert suite.manifest.token_budget is None
    assert suite.scenarios == []
