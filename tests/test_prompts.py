from app.config import MAX_CONTEXT_CHARS
from app.prompts import build_context
from test_chat import hit


def test_context_limit_includes_metadata_and_sources_match_sent_text():
    context, sources = build_context([hit("a" * 5000), hit("b" * 5000, 22), hit("c" * 5000, 23)])
    assert len(context) == MAX_CONTEXT_CHARS
    assert [source.id for source in sources] == ["S1", "S2"]
    assert "[S3]" not in context and "Página física: 22" in context
    assert sources[1].excerpt == "b" * 600
    assert len(sources[0].excerpt) == 600


def test_unusable_text_does_not_create_sources():
    assert build_context([hit(" \n\t")]) == ("", [])


def test_context_empty_when_no_room_for_reference():
    item = hit("conteúdo")
    item["chunk"]["document_name"] = "x" * MAX_CONTEXT_CHARS
    assert build_context([item]) == ("", [])
