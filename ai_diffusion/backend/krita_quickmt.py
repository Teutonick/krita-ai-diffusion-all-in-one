"""ComfyUI node and local endpoint for QuickMT translation into English."""

import asyncio
import hashlib
import json
import logging
import os
import re
from importlib import import_module
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from urllib.request import urlopen

models = json.loads(
    Path(__file__).with_name("krita_quickmt_models.json").read_text(encoding="utf-8")
)

_lock = Lock()
_engine = None
_engine_language = ""
_directive = re.compile(r"(?<!\w)lang:([a-z]{2})(?!\w)")
_sentence_end = re.compile(r"(?:[.!?…;]+(?=\s|$)|[。！？；]+)")
_protected = re.compile(
    rf"(<[^<>\r\n]+>|embedding:[^\s,]*[^\s,.!?…;]|@[\w-]+(?:\.[\w-]+)*"
    rf"|\[Box[^\]\r\n]*\]|\r?\n|{_sentence_end.pattern})"
)
_cyrillic = re.compile(r"[\u0400-\u052f]")
_word = re.compile(r"\b\w+\b")
log = logging.getLogger(__name__)


def _is_repeated_word(text: str):
    words = _word.findall(text.casefold())
    return len(words) >= 3 and len(set(words)) == 1


def ensure_model(folder: Path, language: str):
    model = models[language]
    source = f"https://huggingface.co/quickmt/quickmt-{language}-en/resolve/{model['revision']}"
    folder.mkdir(parents=True, exist_ok=True)
    for name, (size, checksum) in model["files"].items():
        path = folder / name
        if path.is_file() and path.stat().st_size == size:
            continue
        with NamedTemporaryFile(dir=folder, suffix=".part", delete=False) as scratch:
            temporary = Path(scratch.name)
        try:
            digest = hashlib.sha256()
            received = 0
            with (
                urlopen(f"{source}/{name}", timeout=30) as response,
                temporary.open("wb") as output,
            ):
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > size:
                        raise RuntimeError(f"QuickMT download exceeded expected size for {name}")
                    digest.update(block)
                    output.write(block)
            if received != size or (checksum and digest.hexdigest() != checksum):
                raise RuntimeError(f"QuickMT download failed verification for {name}")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


class QuickMT:
    def __init__(self, folder: Path):
        import ctranslate2  # pyright: ignore[reportMissingImports]
        import sentencepiece  # pyright: ignore[reportMissingImports]

        self.translator = ctranslate2.Translator(
            str(folder), device="cpu", compute_type="int8", inter_threads=1, intra_threads=4
        )
        self.source = sentencepiece.SentencePieceProcessor(model_file=str(folder / "src.spm.model"))
        self.target = sentencepiece.SentencePieceProcessor(model_file=str(folder / "tgt.spm.model"))

    def translate(self, text: list[str]):
        tokens = [self.source.encode(chunk, out_type=str) + ["</s>"] for chunk in text]
        output = self._decode(tokens, beam=2)
        repeated = [
            i
            for i, (source, result) in enumerate(zip(text, output, strict=True))
            if _is_repeated_word(result) and not _is_repeated_word(source)
        ]
        if repeated:
            log.warning("QuickMT repeated one word in %d segment(s); retrying", len(repeated))
            results = self._decode([tokens[i] for i in repeated], beam=1)
            for i, result in zip(repeated, results, strict=True):
                output[i] = result if result.strip() and not _is_repeated_word(result) else text[i]
        return output

    def _decode(self, tokens: list[list[str]], *, beam: int):
        results = self.translator.translate_batch(
            tokens,
            beam_size=beam,
            max_batch_size=8,
            max_input_length=0,
            max_decoding_length=1024,
        )
        return [self.target.decode(result.hypotheses[0]) for result in results]


def engine(language: str):
    global _engine, _engine_language
    with _lock:
        if _engine is None or _engine_language != language:
            import folder_paths  # pyright: ignore[reportMissingImports]

            cache = Path(
                os.environ.get(
                    "KRITA_QUICKMT_MODELS", Path(folder_paths.models_dir) / "translation"
                )
            )
            revision = models[language]["revision"]
            folder = cache / f"quickmt-{language}-en-{revision[:7]}"
            ensure_model(folder, language)
            _engine = None
            _engine = QuickMT(folder)
            _engine_language = language
    return _engine


def translate(text: str, language="en"):
    parts = _directive.split(text)
    chunks: list[str] = []
    pending: dict[str, list[tuple[int, str, str, str]]] = {}
    if language != "en" and language not in models:
        raise ValueError(f"QuickMT does not support translation from {language}")
    for index, part in enumerate(parts):
        if index % 2:
            language = part
            if language != "en" and language not in models:
                raise ValueError(f"QuickMT does not support translation from {language}")
            part = parts[index + 1]
            if part.startswith(" "):
                parts[index + 1] = part[1:]
            continue
        for chunk_index, chunk in enumerate(_protected.split(part)):
            if (
                language != "en"
                and chunk_index % 2 == 0
                and any(c.isalpha() for c in chunk)
                and (language != "ru" or _cyrillic.search(chunk))
            ):
                content = chunk.strip()
                prefix = chunk[: len(chunk) - len(chunk.lstrip())]
                suffix = chunk[len(chunk.rstrip()) :]
                pending.setdefault(language, []).append((len(chunks), content, prefix, suffix))
            chunks.append(chunk)

    for language, phrases in pending.items():
        results = engine(language).translate([item[1] for item in phrases])
        for (index, original, prefix, suffix), result in zip(phrases, results, strict=True):
            result = result.strip()
            if index + 1 < len(chunks) and _sentence_end.fullmatch(chunks[index + 1]):
                result = result.rstrip(".!?…;。！？；").rstrip()
            chunks[index] = prefix + (result or original) + suffix
    return "".join(chunks)


class KritaQuickMTTranslate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"multiline": True})}}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "translate"
    CATEGORY = "Krita"

    def translate(self, text):
        return (translate(text),)


NODE_CLASS_MAPPINGS = {"KritaQuickMTTranslate": KritaQuickMTTranslate}


def _register_route():
    try:
        from aiohttp import web

        prompt_server = getattr(import_module("server"), "PromptServer", None)
    except ImportError:
        return
    if prompt_server is None:
        return

    @prompt_server.instance.routes.get("/api/krita/quickmt/languages")
    async def translation_languages(_request):
        return web.json_response([
            {"code": code, "name": model["name"]} for code, model in models.items()
        ])

    @prompt_server.instance.routes.post("/api/krita/quickmt/translate")
    async def translate_request(request):
        data = await request.json()
        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
            raise web.HTTPBadRequest(text="Expected a text field")
        language = data.get("language", "ru")
        if not isinstance(language, str) or language not in models:
            raise web.HTTPBadRequest(text="Unsupported QuickMT source language")
        return web.json_response(await asyncio.to_thread(translate, data["text"], language))


_register_route()
