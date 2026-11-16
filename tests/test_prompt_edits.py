import json

import pytest

from ai_diffusion.backend.ollama import apply_prompt_edits


def edit_response(*pairs, negative=""):
    return json.dumps({
        "edits": [{"find": find, "replace": replace} for find, replace in pairs],
        "negative": negative,
    })


def test_preserves_layout_and_protected_tokens():
    source = "# Scene\n<lora:cars:1>,  blue car, __street__, rain\n# Lighting\nNeon"
    response = edit_response(("blue car", "red car"), (", rain", ""), negative="rain")
    result, negative = apply_prompt_edits(source, response)
    assert result == "# Scene\n<lora:cars:1>,  red car, __street__\n# Lighting\nNeon"
    assert negative == "rain"


def test_append():
    assert apply_prompt_edits("a car,", edit_response(("", "red paint"))) == (
        "a car, red paint",
        "",
    )


@pytest.mark.parametrize(
    "response",
    [
        "A new, rewritten prompt",
        edit_response(("blue car, car, __street__", "a rewritten prompt")),
        edit_response(("car", "truck")),
        edit_response(("green", "red")),
        edit_response(("blue car", "red car"), ("blue", "yellow")),
        edit_response(("street", "road")),
    ],
)
def test_rejects_unusable_edits(response):
    with pytest.raises(ValueError):
        apply_prompt_edits("blue car, car, __street__", response)
