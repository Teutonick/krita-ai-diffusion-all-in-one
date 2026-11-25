import json
import re

from ..image import Bounds, Extent
from ..text import merge_prompt

_box_line = re.compile(r"^\[Box (\d+),(\d+),(\d+),(\d+)\] (.+)$")
edit_lora = "moss_image_edit_lora_rank_64_bf16.safetensors"


def is_edit_lora(name: str):
    return name.replace("\\", "/").rsplit("/", 1)[-1].lower() == edit_lora


def box_prompt(bounds: Bounds, extent: Extent, caption: str):
    x, y, w, h = Bounds.clamp(bounds, extent)
    edges = (y / extent.height, x / extent.width, (y + h) / extent.height, (x + w) / extent.width)
    return "[Box " + ",".join(str(round(edge * 10000)) for edge in edges) + "] " + caption


def split_prompt(prompt: str):
    summary, boxes = [], []
    for line in prompt.splitlines():
        match = _box_line.fullmatch(line.strip())
        if match is None:
            summary.append(line)
            continue
        top, left, bottom, right = map(int, match.groups()[:4])
        if not (0 <= top < bottom <= 10000 and 0 <= left < right <= 10000):
            raise ValueError("Invalid MOSS prompt box bounds.")
        boxes.append(((top, left, bottom, right), match[5]))
    return "\n".join(summary).strip(), boxes


def has_boxes(prompt: str):
    return any(_box_line.fullmatch(line.strip()) for line in prompt.splitlines())


def caption_at(prompt: str, start: int, end: int):
    offset = 0
    for line in prompt.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        caption_line = body.strip()
        if offset <= start <= end <= offset + len(body):
            if match := _box_line.fullmatch(caption_line):
                caption_start = offset + len(body) - len(body.lstrip()) + match.start(5)
                return (caption_start, offset + len(body.rstrip())), tuple(
                    int(match[index]) for index in range(1, 5)
                )
            break
        offset += len(line)
    return None


def compile_layout(prompt: str, extent: Extent, style: str = ""):
    summary, boxes = split_prompt(prompt)
    items = []
    for edges, caption in boxes:
        bbox = [
            round(edge * size / 10000) - size // 2
            for edge, size in zip(
                edges,
                (extent.height, extent.width, extent.height, extent.width),
            )
        ]
        items.append({"label": "object", "caption": caption, "bbox": bbox})
    if items:
        return json.dumps(
            {
                "summary": {"caption": merge_prompt(summary, style)},
                "items": items,
                "bbox_coord_space": "abs_centralized",
                "bbox_format": "yxyx",
            },
            ensure_ascii=False,
        )
    return None
