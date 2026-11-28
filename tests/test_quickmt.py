from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ai_diffusion.backend import krita_quickmt
from ai_diffusion.backend.client import ClientFeatures, TranslationPackage
from ai_diffusion.backend.comfy_client import ComfyClient
from ai_diffusion.backend.comfy_workflow import ComfyWorkflow
from ai_diffusion.backend.lora_manager import LoraInfo, save_lora_cache

from .conftest import qtapp


def test_translation_preserves_prompt_syntax_and_batches_text(monkeypatch):
    run = Mock(return_value=["red scarf", "cold light"])
    monkeypatch.setattr(krita_quickmt, "engine", lambda _: SimpleNamespace(translate=run))
    text = "Keep the style\nlang:ru красный шарф @hero <lora:look:0.7>\nхолодный свет embedding:test lang:en daylight"
    assert krita_quickmt.translate(text) == (
        "Keep the style\nred scarf @hero <lora:look:0.7>\ncold light embedding:test daylight"
    )
    run.assert_called_once_with(["красный шарф", "холодный свет"])


def test_english_and_prompt_tokens_do_not_load_the_engine(monkeypatch):
    engine = Mock(side_effect=AssertionError("unnecessary model load"))
    monkeypatch.setattr(krita_quickmt, "engine", engine)
    assert krita_quickmt.translate("Use @персонаж in daylight", "ru") == "Use @персонаж in daylight"
    with pytest.raises(ValueError, match="does not support"):
        krita_quickmt.translate("lang:xx Hallo")
    engine.assert_not_called()


def test_english_and_ids_in_mixed_russian_prompt(monkeypatch):
    run = Mock(return_value=["blue light", "snow"])
    monkeypatch.setattr(krita_quickmt, "engine", lambda _: SimpleNamespace(translate=run))
    assert (
        krita_quickmt.translate("синий свет cinematic photography ABC123 v2. снег", "ru")
        == "blue light cinematic photography ABC123 v2. snow"
    )
    run.assert_called_once_with(["синий свет", "снег"])


def test_language_identifier_preserves_english_with_french_selected(monkeypatch):
    identifier = SimpleNamespace(
        classify={"studio lighting": ("en", 0.99), "rose bleue": ("fr", 0.95)}.__getitem__
    )
    monkeypatch.setattr(krita_quickmt, "_language_identifier", lambda: identifier)
    run = Mock(return_value=["blue rose"])
    monkeypatch.setattr(krita_quickmt, "engine", lambda _: SimpleNamespace(translate=run))
    assert krita_quickmt.translate("studio lighting. rose bleue XJ23A", "fr") == (
        "studio lighting. blue rose XJ23A"
    )
    run.assert_called_once_with(["rose bleue"])


@pytest.mark.parametrize(
    "retry, expected",
    [
        ("cinematic staged photo", "cinematic staged photo"),
        ("photo photo photo", "кинематографичное постановочное фото"),
    ],
)
def test_quickmt_retries_repeated_words_only(monkeypatch, retry, expected):
    translator = krita_quickmt.QuickMT.__new__(krita_quickmt.QuickMT)
    translator.source = SimpleNamespace(encode=lambda text, **_: text.split())
    decode = Mock(side_effect=[["photo photo photo.", "blue rose", "no no no"], [retry]])
    monkeypatch.setattr(translator, "_decode", decode)
    assert translator.translate([
        "кинематографичное постановочное фото",
        "синяя роза",
        "нет нет нет",
    ]) == [expected, "blue rose", "no no no"]
    decode.assert_called_with([["кинематографичное", "постановочное", "фото", "</s>"]], beam=1)


def test_translation_preserves_sentence_separators(monkeypatch):
    run = Mock(return_value=["blue rose", "three trees.", "warm light!"])
    monkeypatch.setattr(krita_quickmt, "engine", lambda _: SimpleNamespace(translate=run))
    text = "синяя роза.  три дерева; тёплый свет?!"
    expected = "blue rose.  three trees; warm light?!"
    assert krita_quickmt.translate(text, "ru") == expected
    assert krita_quickmt.translate(f"lang:ru {text} lang:en", "en") == expected + " "
    run.assert_called_with(["синяя роза", "три дерева", "тёплый свет"])


def test_translation_routes_each_language_to_its_model(monkeypatch):
    french = Mock(return_value=["blue rose"])
    japanese = Mock(return_value=["cold light", "warm light"])
    get_engine = Mock(
        side_effect={
            "fr": SimpleNamespace(translate=french),
            "ja": SimpleNamespace(translate=japanese),
        }.__getitem__
    )
    monkeypatch.setattr(krita_quickmt, "engine", get_engine)
    assert krita_quickmt.translate("lang:fr rose bleue. lang:ja 冷たい光。暖かい光！") == (
        "blue rose. cold light。warm light！"
    )
    french.assert_called_once_with(["rose bleue"])
    japanese.assert_called_once_with(["冷たい光", "暖かい光"])


def test_workflow_translation_preserves_lora_trigger_words(monkeypatch):
    run = Mock(return_value=["very cold", "with snow"])
    monkeypatch.setattr(krita_quickmt, "engine", lambda _: SimpleNamespace(translate=run))
    workflow = ComfyWorkflow()
    workflow.protected_lora_triggers = ["Blue", "Blue.Rose", "синий огонь"]
    workflow.translate("lang:ru очень холодный Blue.Rose синий огонь со снегом.")
    inputs = next(iter(workflow.root.values()))["inputs"]
    assert krita_quickmt.KritaQuickMTTranslate().translate(**inputs) == (
        "very cold Blue.Rose синий огонь with snow.",
    )
    run.assert_called_once_with(["очень холодный", "со снегом"])


@qtapp
async def test_manual_translation_sends_json_to_quickmt(monkeypatch):
    client = ComfyClient("http://localhost:8188")
    client._features = ClientFeatures(
        translation=True, languages=[TranslationPackage("fr", "French")]
    )
    post = AsyncMock(return_value="cold light")
    monkeypatch.setattr(client, "_post", post)
    assert await client.translate("lumière froide", "fr") == "cold light"
    post.assert_awaited_once_with(
        "api/krita/quickmt/translate", {"text": "lumière froide", "language": "fr"}
    )
    assert await client.translate("текст", "ru") == "текст"
    assert post.await_count == 1


@qtapp
async def test_manual_translation_protects_selected_lora_triggers(monkeypatch):
    client = ComfyClient("http://localhost:18188")
    client._features = ClientFeatures(
        translation=True, languages=[TranslationPackage("fr", "French")]
    )
    save_lora_cache(
        client.url,
        [
            LoraInfo("look", trigger_words=["Blue.Rose, RedGlow"]),
            LoraInfo("other", trigger_words=["irrelevant"]),
        ],
    )
    post = AsyncMock(return_value="<lora:look:0.8> Blue.Rose cold light")
    monkeypatch.setattr(client, "_post", post)
    prompt = "<lora:look:0.8> Blue.Rose lumière froide"
    await client.translate(prompt, "fr")
    post.assert_awaited_once_with(
        "api/krita/quickmt/translate",
        {
            "text": prompt,
            "language": "fr",
            "protected": ["Blue.Rose", "Blue.Rose, RedGlow", "RedGlow"],
        },
    )
