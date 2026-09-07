from core.json_extraction import iter_json_objects


def test_finds_a_bare_json_object():
    assert list(iter_json_objects('{"a": 1}')) == [{"a": 1}]


def test_finds_json_object_wrapped_in_prose_before_and_after():
    text = 'We think the shape is {"a": 1} so here it is: {"a": 1}. Done.'
    assert list(iter_json_objects(text)) == [{"a": 1}, {"a": 1}]


def test_ignores_unbalanced_braces_in_surrounding_prose():
    text = 'Note: the shape { is roughly like this }\nHere is the real one: {"a": 1}'
    assert list(iter_json_objects(text)) == [{"a": 1}]


def test_braces_inside_json_strings_do_not_confuse_extent():
    text = 'commentary {{{ {"a": "value with a } brace"} more text'
    assert list(iter_json_objects(text)) == [{"a": "value with a } brace"}]


def test_no_json_object_yields_nothing():
    assert list(iter_json_objects("just some plain text")) == []


def test_ignores_a_bare_json_array_at_top_level():
    assert list(iter_json_objects("[1, 2, 3]")) == []
