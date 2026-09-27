from evaluations.preset_enterprise_proof import _parse_json_output


def test_proof_reviewer_output_parser_accepts_json_with_prefix() -> None:
    assert _parse_json_output('review complete\n{"passed": true}') == {"passed": True}


def test_proof_reviewer_output_parser_rejects_trailing_text() -> None:
    assert _parse_json_output('{"passed": true}\nreview complete') is None
