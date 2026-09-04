from benchmark.types import FaultStep

PRODUCT = {"id": 7, "name": "Keyboard", "price": 49.5}

T1_SCENARIOS = {
    "clean": [FaultStep(status=200, json_body=PRODUCT)],
    "transient_503": [FaultStep(status=503), FaultStep(status=503), FaultStep(status=200, json_body=PRODUCT)],
    "persistent_503": [FaultStep(status=503)],
    "timeout": [FaultStep(error="timeout", delay_s=0.25)],
    "rate_limit": [FaultStep(status=429, headers={"Retry-After": "0"}), FaultStep(status=200, json_body=PRODUCT)],
    "malformed_200": [FaultStep(status=200, raw_body=b'{"id": 7, "price": "oops"}')],
}

CHARGE = {"charge_id": "ch_1", "status": "captured"}
T4_SCENARIOS = {
    "clean": [FaultStep(status=200, json_body=CHARGE, commits=True)],
    "transient_503": [FaultStep(status=503), FaultStep(status=503), FaultStep(status=200, json_body=CHARGE, commits=True)],
    "persistent_503": [FaultStep(status=503)],
    "timeout_before_commit": [FaultStep(error="timeout", delay_s=0.25), FaultStep(status=200, json_body=CHARGE, commits=True)],
    "rate_limit": [FaultStep(status=429, headers={"Retry-After": "0"}), FaultStep(status=200, json_body=CHARGE, commits=True)],
    "malformed_200": [FaultStep(status=200, raw_body=b'{"charge_id": 3}', commits=True)],
    "committed_response_lost": [FaultStep(error="timeout", commits=True, delay_s=0.25), FaultStep(status=200, commits=True)],
}
