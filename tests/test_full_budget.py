from benchmark.full_generate import reservation,charge,load_spend

def test_budget_reserves_incomplete_calls_and_reconciles_completed_usage():
    rows=[{'event':'start','attempt_id':'a','reserved':.3},{'event':'start','attempt_id':'b','reserved':.3},{'event':'finish','attempt_id':'a','charged':.05}]
    assert abs(load_spend(rows)-.35)<1e-9

def test_reservation_covers_full_output_and_usage_is_not_double_counted():
    r=reservation('abc','Anthropic')
    assert r>=.30
    assert charge({'usage':{'input_tokens':1000,'output_tokens':1000,'output_tokens_details':{'thinking_tokens':500}}},'Anthropic')==.03
