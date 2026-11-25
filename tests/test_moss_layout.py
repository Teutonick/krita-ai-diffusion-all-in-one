import json

from ai_diffusion.backend.moss_layout import box_prompt, caption_at, compile_layout, split_prompt
from ai_diffusion.image import Bounds, Extent


def test_two_boxes_follow_generation_size():
    canvas = Extent(1000, 800)
    prompt = "\n".join((
        "A garden",
        box_prompt(Bounds(100, 200, 200, 400), canvas, "A rose"),
        box_prompt(Bounds(500, 0, 500, 400), canvas, "A tree"),
    ))
    result = compile_layout(prompt, Extent(500, 400), "soft light")
    assert result is not None
    layout = json.loads(result)
    assert layout["summary"]["caption"] == "A garden, soft light"
    assert layout["items"] == [
        {"label": "object", "caption": "A rose", "bbox": [-100, -200, 100, -100]},
        {"label": "object", "caption": "A tree", "bbox": [-200, 0, 0, 250]},
    ]
    assert compile_layout("A garden", canvas) is None


def test_ai_caption_span_preserves_coordinates_and_other_lines():
    original = "A garden 🌿\n[Box 0,0,5000,5000] A rose\n  [Box 5000,5000,10000,10000] A tree  "
    position = original.index("tree")
    target = caption_at(original, position, position)
    assert target is not None
    (start, end), edges = target
    assert original[start:end] == "A tree"
    assert edges == (5000, 5000, 10000, 10000)
    result = original[:start] + "A tall oak" + original[end:]
    assert split_prompt(result) == (
        "A garden 🌿",
        [((0, 0, 5000, 5000), "A rose"), (edges, "A tall oak")],
    )
    assert caption_at(original, 0, 0) is None
    assert caption_at(original, original.index("rose"), position) is None
