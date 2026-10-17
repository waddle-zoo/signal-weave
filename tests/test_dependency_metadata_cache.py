"""Metadata reuse never crosses parameters, principals or successive checks."""

import pytest

from tests.test_context_dependencies import NOW, READER, add_note, make_ref, make_services


async def test_shared_source_metadata_is_reused_only_within_one_dependency_check(tmp_path):
    knowledge, dependencies, (adapter,) = make_services(tmp_path)
    add_note(knowledge, entry_id="definition")
    add_note(knowledge, entry_id="exception")
    pins = [await dependencies.pin(entry_id, 1, READER, now=NOW)
            for entry_id in ("definition", "exception")]
    adapter.authorization_calls.clear()
    assert (await dependencies.inspect(pins, READER, now=NOW))["all_current"]
    assert len(adapter.authorization_calls) == 1
    adapter.denied.add((READER.tenant_id, "chart:net-sales"))
    checked = await dependencies.inspect(pins, READER, now=NOW)
    assert not checked["all_current"]
    assert {item["status"] for item in checked["entries"]} == {"unavailable"}


async def test_same_locator_different_parameters_does_not_share_metadata_cache(tmp_path):
    knowledge, dependencies, (adapter,) = make_services(tmp_path)
    pins = []
    for name, scope in (("one", "enterprise"), ("two", "small-business")):
        add_note(knowledge, entry_id=name, sources=[make_ref(parameters={"scope": scope})])
        pins.append(await dependencies.pin(name, 1, READER, now=NOW))
    adapter.authorization_calls.clear()
    assert (await dependencies.inspect(pins, READER, now=NOW))["all_current"]
    assert len(adapter.authorization_calls) == 2


async def test_binding_does_not_expose_private_connector_diagnostics(tmp_path):
    knowledge, dependencies, (adapter,) = make_services(tmp_path)
    add_note(knowledge)

    async def failed_authorization(*args, **kwargs):
        raise ValueError("PRIVATE_ENDPOINT_TOKEN_SENTINEL")

    adapter.authorize = failed_authorization
    with pytest.raises(ValueError, match="source identity unavailable") as error:
        await dependencies.pin("context-1", 1, READER, now=NOW)
    assert "PRIVATE_ENDPOINT_TOKEN_SENTINEL" not in str(error.value)
