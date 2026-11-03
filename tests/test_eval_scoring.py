from copilot.eval.run_eval import passes


def test_relative_tolerance():
    assert passes(251_463, 251_463.0, {})
    assert passes(1_268_000, 1_267_942.7, {})
    assert not passes(1_300_000, 1_267_942.7, {})


def test_share_given_as_percent_is_accepted():
    assert passes(19.92, 0.19918, {})
    assert not passes(25.0, 0.19918, {})


def test_absolute_tolerance_and_missing_value():
    assert passes(0.011, 0.010875, {"abs_tol": 0.002})
    assert not passes(0.02, 0.010875, {"abs_tol": 0.002})
    assert not passes(None, 1.0, {})
