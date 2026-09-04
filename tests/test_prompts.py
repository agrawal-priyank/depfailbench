from benchmark.prompts import compose_prompt, prompt_sha256


def test_all_pilot_prompts_are_frozen_and_distinct():
    hashes = set()
    for task in ("T1", "T4"):
        for condition in ("C0", "C1"):
            prompt = compose_prompt(task, condition)
            assert "create_app(transport, settings=None)" in prompt
            hashes.add(prompt_sha256(prompt))
    assert len(hashes) == 4


def test_c0_does_not_disclose_faultload_requirements():
    t1 = compose_prompt("T1", "C0").lower()
    assert "retry transient" not in t1
    assert "timeout" not in t1
    t4 = compose_prompt("T4", "C0").lower()
    assert "lost response" not in t4
    assert "ambiguous" not in t4


def test_t4_state_contract_is_visible_in_both_conditions():
    for condition in ("C0", "C1"):
        assert "app.state.orders" in compose_prompt("T4", condition)
