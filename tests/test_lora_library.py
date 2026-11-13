from typing import cast
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

from ai_diffusion.backend.lora_manager import LoraInfo, fetch_loras_pages
from ai_diffusion.ui.content_rating import ALL, NSFW, SFW, matches_content_rating

from .conftest import qtapp


@qtapp
async def test_incomplete_manager_list_includes_all_comfy_files():
    requests = AsyncMock()

    async def get(url, **kwargs):
        if "favorites_only" in url:
            return {"items": []}
        if "/api/lm/loras/list" in url:
            return {
                "items": [{"file_name": "known.safetensors", "folder": "Krea2", "sha256": "abc"}],
                "total": 1,
            }
        return ["krea2\\known.safetensors", "Krea2/missing.SAFETENSORS", "private.safetensors"]

    requests.get.side_effect = get
    loras = [lora async for batch in fetch_loras_pages(requests, "http://server") for lora in batch]
    assert [l.name for l in loras] == ["Krea2/known", "Krea2/missing", "private"]
    assert loras[0].sha256 == "abc"
    assert all(not l.preview_url for l in loras)


@qtapp
async def test_unavailable_manager_keeps_standard_library():
    requests = AsyncMock()

    async def get(url, **kwargs):
        if "/api/lm/" in url:
            raise RuntimeError("unavailable")
        return ["private.safetensors"]

    requests.get.side_effect = get
    loras = [lora async for batch in fetch_loras_pages(requests, "http://server") for lora in batch]
    assert [l.name for l in loras] == ["private"]


def test_manager_folder_is_not_duplicated():
    assert (
        LoraInfo.from_api({"file_name": "Krea2/model.safetensors", "folder": "Krea2"}, "").name
        == "Krea2/model"
    )


def test_rating_filter_uses_the_selected_preview():
    data = {
        "file_name": "model.safetensors",
        "preview_nsfw_level": 2,
        "civitai": {"images": [{"url": "https://image.civitai.com/preview.png", "nsfwLevel": 8}]},
    }
    rated = LoraInfo.from_api(data, "").nsfw_level
    unrated = LoraInfo.from_api({"file_name": "local.safetensors"}, "").nsfw_level
    assert not matches_content_rating(SFW, rated)
    assert matches_content_rating(NSFW, rated)
    assert matches_content_rating(SFW, 2)
    assert not matches_content_rating(NSFW, 2)
    assert not matches_content_rating(SFW, unrated)
    assert not matches_content_rating(NSFW, unrated)
    assert matches_content_rating(ALL, unrated)


@qtapp
async def test_scan_enriches_triggers_even_with_existing_preview(monkeypatch, tmp_path):
    from ai_diffusion.backend import civitai
    from ai_diffusion.backend import lora_manager as lm

    requests = AsyncMock()
    requests.get.return_value = {
        "trainedWords": ["identity", "portrait", None],
        "baseModel": "Krea 2",
        "images": [],
    }
    monkeypatch.setattr(civitai, "requests", lambda: requests)
    monkeypatch.setattr(lm.util, "user_data_dir", tmp_path)
    lora = LoraInfo("model", sha256="abc", preview_url="https://example.com/preview.png")
    await lm.enrich_lora_metadata([lora])
    assert lora.trigger_words == ["identity", "portrait"]
    assert lora.base_model == "Krea 2"
    lm.save_lora_cache("http://server", [lora])
    cached = lm.load_cached_loras("http://server")
    assert cached is not None
    assert cached[0].trigger_words == lora.trigger_words
    assert list(tmp_path.iterdir()) == []
    lm._memory_cache.clear()
    assert lm.load_cached_loras("http://server") is None


@qtapp
async def test_metadata_failure_keeps_local_lora(monkeypatch):
    from ai_diffusion.backend import civitai
    from ai_diffusion.backend import lora_manager as lm

    requests = AsyncMock()
    requests.get.side_effect = RuntimeError("not found")
    monkeypatch.setattr(civitai, "requests", lambda: requests)
    lora = LoraInfo("private", sha256="unknown")
    await lm.enrich_lora_metadata([lora])
    assert lora.name == "private" and lora.trigger_words == []


def test_add_lora_uses_active_prompt(monkeypatch):
    from types import SimpleNamespace as NS
    from unittest.mock import Mock

    __import__("ai_diffusion.model.model")
    from ai_diffusion.ui import lora_picker

    generate = NS(positive="generate")
    edit = NS(positive="edit")
    model = NS(regions=NS(active_or_root=generate), active_regions=NS(active_or_root=edit))
    monkeypatch.setattr(lora_picker, "root", NS(active_model=model))
    item = Mock()
    item.data.return_value = LoraInfo("model")
    browser = NS(
        _grid=NS(selectedItems=lambda: [item]),
        _build_addition=lambda: "<lora:model:1.00> trigger",
        lora_selected=Mock(),
        _strength=NS(value=lambda: 1.0),
        _position_combo=NS(currentData=lambda: lora_picker._POS_END),
    )
    lora_picker.LoraBrowser._add_to_prompt(cast(lora_picker.LoraBrowser, browser))
    assert edit.positive == "edit\n<lora:model:1.00> trigger"
    assert generate.positive == "generate"
    model.active_regions = model.regions
    lora_picker.LoraBrowser._add_to_prompt(cast(lora_picker.LoraBrowser, browser))
    assert generate.positive == "generate\n<lora:model:1.00> trigger"


def test_base_model_filter_excludes_unknown_and_other_architectures():
    from types import SimpleNamespace as NS

    __import__("ai_diffusion.model.model")
    from ai_diffusion.ui import lora_picker

    loras = [
        LoraInfo("krea", base_model="Krea 2"),
        LoraInfo("flux", base_model="Flux.1 D"),
        LoraInfo("unknown", base_model="Unknown"),
        LoraInfo("missing"),
    ]
    browser = NS(
        _search=NS(text=lambda: ""),
        _arch_combo=NS(currentData=lambda: "krea2"),
        _tag_combo=NS(currentData=lambda: lora_picker._TAG_ALL),
        _favorites_only=NS(isChecked=lambda: False),
        _nsfw_combo=NS(currentData=lambda: ALL),
        _sort_combo=NS(currentData=lambda: None),
        _all_loras=loras,
        _populate_grid=lambda: None,
    )
    lora_picker.LoraBrowser._apply_filter(cast(lora_picker.LoraBrowser, browser))
    assert [l.name for l in browser._filtered] == ["krea"]
    browser._arch_combo.currentData = lambda: lora_picker._ARCH_ANY
    lora_picker.LoraBrowser._apply_filter(cast(lora_picker.LoraBrowser, browser))
    assert len(browser._filtered) == 4


@qtapp
async def test_civitai_h3_lora_filter_uses_video_base_label(monkeypatch):
    from ai_diffusion.backend import civitai
    from ai_diffusion.backend.lora_manager import arch_for_base_model

    request = AsyncMock()
    request.get.return_value = {"items": []}
    monkeypatch.setattr(civitai, "requests", lambda: request)
    await civitai.search_models(base_models=civitai.civitai_base_models["minimax_h3_image"])
    url = request.get.call_args.args[0]
    assert parse_qs(urlsplit(url).query)["baseModels"] == ["MiniMax H3"]
    assert arch_for_base_model("MiniMax H3 (FL2VA)") == "minimax_h3_image"
    assert arch_for_base_model("minimax_h3_image") == "minimax_h3_image"
