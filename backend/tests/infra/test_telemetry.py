from infra.telemetry import trace_id_var, trace_scope


def test_trace_scope_sets_and_restores_nested_trace_id():
    assert trace_id_var.get() is None

    with trace_scope("outer"):
        assert trace_id_var.get() == "outer"
        with trace_scope("inner"):
            assert trace_id_var.get() == "inner"
        assert trace_id_var.get() == "outer"

    assert trace_id_var.get() is None
