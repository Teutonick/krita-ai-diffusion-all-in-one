from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ai_diffusion.backend import krita_quickmt
from ai_diffusion.backend.client import ClientFeatures, TranslationPackage
from ai_diffusion.backend.comfy_client import ComfyClient

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
