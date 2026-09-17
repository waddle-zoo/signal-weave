from semantic_monitor.mcp_server import create_mcp


def test_server_exposes_mcp_object():
    server = create_mcp()
    assert server.name == "signal-weave"
