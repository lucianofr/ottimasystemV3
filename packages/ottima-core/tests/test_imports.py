def test_workspace_packages_importaveis():
    import ottima_api
    import ottima_core
    import ottima_flow_runtime
    import ottima_opc_worker
    import ottima_recorder

    assert ottima_core.__doc__
    assert ottima_api.__doc__
    assert ottima_opc_worker.__doc__
    assert ottima_flow_runtime.__doc__
    assert ottima_recorder.__doc__
