import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest
import requests

from ai_diffusion.backend import moss_layout, pov, workflow
from ai_diffusion.backend.api import (
    CheckpointInput,
    ConditioningInput,
    ControlInput,
    ImageInput,
    InpaintMode,
    InpaintParams,
    LoraInput,
    SamplingInput,
    WorkflowInput,
    WorkflowKind,
)
from ai_diffusion.backend.client import CheckpointInfo, ClientModels
from ai_diffusion.backend.comfy_workflow import ComfyObjectInfo
from ai_diffusion.backend.resources import Arch, ControlMode, ResourceKind, resource_id
from ai_diffusion.files import File, FileCollection, FileFormat, FileLibrary
from ai_diffusion.image import Bounds, Extent, Image
from ai_diffusion.pose_studio import PoseScene
from ai_diffusion.settings import PerformanceSettings
from ai_diffusion.style import Style
from scripts.check_krea2_server import request

from .config import image_dir, result_dir, root_dir

pov_result_dir = root_dir / ".appdata" / "pov-poc" / "results"


def _edit_work(edit_kind, kind=WorkflowKind.refine, cfg=1.0):
    models = ClientModels()
    checkpoint = "krea2_turbo_fp8_scaled.safetensors"
    models.checkpoints[checkpoint] = CheckpointInfo(checkpoint, Arch.krea2, FileFormat.diffusion)
    models.resources = {
        resource_id(
            ResourceKind.text_encoder, Arch.krea2, "qwen_3vl_4b"
        ): "qwen3vl_4b_fp8_scaled.safetensors",
        resource_id(ResourceKind.vae, Arch.krea2, "default"): "qwen_image_vae.safetensors",
    }
    extent = Extent(512, 512)
    images = ImageInput.from_extent(extent)
    images.initial_image = Image.scale(Image.load(image_dir / "face.webp"), extent)
    work = WorkflowInput(
        kind,
        models=CheckpointInput(
            checkpoint,
            Arch.krea2,
            loras=[LoraInput(f"krea2_{edit_kind}_edit_v2.safetensors", 1.0)],
        ),
        images=images,
        conditioning=ConditioningInput(
            "Keep the same person and facial features. Change only the background to a sunlit garden.",
            edit_reference=True,
        ),
        sampling=SamplingInput("euler", "simple", cfg, 8, seed=1234),
    )
    if kind is WorkflowKind.refine_region:
        images.hires_mask = Image.create(extent, 255)
        work.inpaint = InpaintParams(InpaintMode.custom, Bounds.from_extent(extent))
    return models, work


@pytest.mark.parametrize("use_boxes", [False, True])
@pytest.mark.parametrize("language", ["", "ru"])
def test_moss_edit_uses_reference_and_compositing_mask(use_boxes, language):
    kind = WorkflowKind.refine if use_boxes else WorkflowKind.refine_region
    models, work = _edit_work("identity", kind, 4)
    checkpoint = "moss_image_sft_int8_convrot.safetensors"
    models.checkpoints[checkpoint] = CheckpointInfo(checkpoint, Arch.moss, FileFormat.diffusion)
    models.resources = {
        resource_id(ResourceKind.text_encoder, Arch.moss, "qwen_3.5_9b"): "qwen.safetensors",
        resource_id(ResourceKind.vae, Arch.moss, "default"): "flux2-vae.safetensors",
    }
    work.models = CheckpointInput(
        checkpoint,
        Arch.moss,
        loras=[LoraInput(moss_layout.edit_lora, 1), LoraInput("character.safetensors", 0.75)],
    )
    assert work.conditioning is not None
    work.conditioning.language = language
    captions = (
        ("солнцезащитные очки", "серебряная пуговица")
        if language
        else ("Make the eye black", "Add a silver button")
    )
    if use_boxes:
        work.conditioning.positive = (
            f"[Box 0,0,5000,5000] {captions[0]}\n[Box 5000,5000,10000,10000] {captions[1]}"
        )
    graph = workflow.create(work, models)
    encoders = [
        node["inputs"]
        for node in graph.root.values()
        if node["class_type"] == "TextEncodeMOSSImageEdit"
    ]
    assert len(encoders) == (3 if use_boxes else 2)
    assert all(encoder["images.image_0"] == encoders[0]["images.image_0"] for encoder in encoders)
    assert all(encoder["edit_format"] == "Moss-Image-Edit" for encoder in encoders)
    output = next(
        node for node in graph.root.values() if node["class_type"] == "ETN_SaveImageCache"
    )
    if use_boxes:
        for encoder, caption in zip(encoders[1:], captions):
            prompt = encoder["prompt"]
            if language:
                translator = graph.root[prompt[0]]
                assert translator["class_type"] == "KritaQuickMTTranslate"
                prompt = translator["inputs"]["text"]
                assert f"lang:ru {caption} lang:en " in prompt
                assert prompt.startswith("Change only the area ")
                assert prompt.endswith("Keep the rest of the image unchanged.")
            else:
                assert caption in prompt
        samplers = [n for n in graph.root.values() if n["class_type"] == "KSampler"]
        assert len(samplers) == 2
        assert samplers[0]["inputs"]["model"] == samplers[1]["inputs"]["model"]
        loras = {
            n["inputs"]["lora_name"]: key
            for key, n in graph.root.items()
            if n["class_type"] == "LoraLoader"
        }
        character = loras["character.safetensors"]
        assert graph.root[character]["inputs"]["model"] == [loras[moss_layout.edit_lora], 0]
        assert graph.root[character]["inputs"]["strength_model"] == 0.75
        assert all(encoder["clip"] == [character, 1] for encoder in encoders)
        sampler_model = graph.root[samplers[0]["inputs"]["model"][0]]
        assert sampler_model["inputs"]["model"] == [character, 0]
        masked_latents = [graph.root[n["inputs"]["latent_image"][0]] for n in samplers]
        assert all(n["class_type"] == "SetLatentNoiseMask" for n in masked_latents)
        first_latent, second_latent = [n["inputs"] for n in masked_latents]
        assert first_latent["samples"] == second_latent["samples"]
        assert first_latent["mask"] != second_latent["mask"]
        assert graph.root[first_latent["samples"][0]]["class_type"] == "VAEEncode"
        patches = [
            (key, node["inputs"])
            for key, node in graph.root.items()
            if node["class_type"] == "ImageCompositeMasked"
        ]
        assert len(patches) == 2
        first, second = patches
        assert first[1]["destination"] == encoders[0]["images.image_0"]
        assert second[1]["destination"] == [first[0], 0]
        assert second[1]["x"] == work.extent.target.width // 2
        assert second[1]["y"] == work.extent.target.height // 2
        assert output["inputs"]["images"] == [second[0], 0]
        return
    assert "mask" in graph.root[output["inputs"]["images"][0]]["inputs"]


@pytest.mark.parametrize("kind", [WorkflowKind.refine, WorkflowKind.refine_region])
@pytest.mark.parametrize("edit_kind", ["identity", "general"])
@pytest.mark.parametrize("cfg", [1.0, 2.0])
def test_krea2_edit_graph(kind, edit_kind, cfg):
    models, work = _edit_work(edit_kind, kind, cfg)
    graph = workflow.create(work, models)
    patches = {key: n for key, n in graph.root.items() if n["class_type"] == "Krea2EditModelPatch"}
    assert len(patches) == 1
    patch_id, patch = next(iter(patches.items()))
    assert patch["inputs"]["ref_boost"] == (2.0 if edit_kind == "identity" else 4.0)
    assert {"source_image", "vae", "target_latent"} <= patch["inputs"].keys()
    assert "source_image_b" not in patch["inputs"]
    assert any(n["inputs"].get("model") == [patch_id, 0] for n in graph.root.values())
    grounded = [n for n in graph.root.values() if n["class_type"] == "Krea2EditGroundedEncode"]
    assert len(grounded) == (2 if cfg > 1 else 1)
    assert all(n["inputs"]["image"] == patch["inputs"]["source_image"] for n in grounded)
    positive = [n["inputs"]["prompt"] for n in grounded if n["inputs"]["prompt"]]
    assert work.conditioning is not None
    assert positive == [work.conditioning.positive]


@pytest.mark.parametrize("keep_loaded", [False, True])
def test_krea2_live_preview_keeps_prompt_lora_translation_and_edit_references(keep_loaded):
    models, template = _edit_work("identity")
    assert template.models
    adapter = f"live/{workflow.krea_live_lora}"
    character = "characters/subject.safetensors"
    models.loras = [adapter, character]
    files = FileLibrary(FileCollection(), FileCollection())
    files.loras.add(File.remote(character))
    style = Style(Path("test.json"))
    style.checkpoints = [template.models.checkpoint]
    target = Extent(1536, 1024)
    source = Image.create(target, fill=0)
    cond = ConditioningInput(
        "Нарисуй @subject <lora:characters/subject:0.7>",
        language="ru",
        edit_reference=True,
        control=[ControlInput(ControlMode.reference, source, name="subject")],
    )
    prepared = workflow.prepare_prompts(cond, style, 42, Arch.krea2, files=files)
    work = workflow.prepare(
        WorkflowKind.refine,
        source,
        prepared.conditioning,
        style,
        42,
        models,
        files,
        PerformanceSettings(),
        loras=prepared.loras,
        fast_preview=True,
    )
    assert work.models and work.models.loras == [LoraInput(character, 0.7), LoraInput(adapter, 1.0)]
    work.models.keep_live_models_loaded = keep_loaded
    assert work.sampling == SamplingInput("euler", "simple", 1.0, 2, seed=42)
    assert work.extent.initial == work.extent.desired == Extent(512, 352)
    assert work.extent.target == target
    assert WorkflowInput.from_dict(work.to_dict()).extent.fast_preview
    graph = workflow.create(work, models)
    nodes = {node["class_type"]: node["inputs"] for node in graph.root.values()}
    assert "ImageUpscaleWithModel" not in nodes
    assert "image 2" in nodes["KritaQuickMTTranslate"]["text"]
    assert "image_b" in nodes["Krea2EditGroundedEncode"]
    assert "source_latent_b" in nodes["Krea2EditModelPatch"]
    assert nodes["BasicScheduler"]["steps"] == 2
    assert ("KritaKeepLiveModelsLoaded" in nodes) is keep_loaded
    if keep_loaded:
        clip = nodes["Krea2EditGroundedEncode"]["clip"]
        assert graph.root[clip[0]]["class_type"] == "KritaKeepLiveModelsLoaded"


def test_make_povs_workflows():
    models, template = _edit_work("identity")
    character_lora = "characters/android.safetensors"
    models.loras = [pov.pov_lora, character_lora]
    models.node_inputs = ComfyObjectInfo({name: {} for name in pov.pov_nodes})
    assert pov.available_models(models) is None
    models.node_inputs.nodes["KritaPOVNormal"] = {
        "input": {"optional": {"subject_context": ["STRING"]}}
    }
    available = pov.available_models(models)
    assert available is not None
    checkpoint, lora = available
    camera_inputs = []
    image_ids = set()
    for _, view in pov.pov_views:
        work = WorkflowInput(
            WorkflowKind.pov,
            images=template.images,
            models=CheckpointInput(
                checkpoint,
                Arch.krea2,
                loras=[LoraInput(lora, 1.0), LoraInput(character_lora, 0.65)],
            ),
            sampling=SamplingInput("euler", "simple", 1.0, 8, seed=1234),
            conditioning=ConditioningInput("Андроид с плоским керамическим лицом", "Human nose"),
            camera_view=view,
        )
        assert WorkflowInput.from_dict(work.to_dict()).camera_view == view
        graph = workflow.create(work, models)
        payload = json.loads(json.dumps({"prompt": graph.root}))
        nodes = {node["class_type"]: node["inputs"] for node in payload["prompt"].values()}
        clip_id, clip_port = nodes["Krea2AnyglesEncode"]["clip"]
        assert payload["prompt"][clip_id]["class_type"] == "LoraLoader"
        assert clip_port == 1
        assert nodes["Krea2AnyglesEncode"]["reference_max_edge"] == 768
        camera_inputs.append(nodes["KritaPOVNormal"]["azimuth"])
        assert nodes["KritaPOVNormal"]["subject_context"] == (
            "Subject and scene description: Андроид с плоским керамическим лицом\n"
            "Avoid these changes or details: Human nose"
        )
        image_ids.add(nodes["ETN_LoadImageCache"]["id"])
        assert "ETN_SaveImageCache" in nodes
        assert {"LoadImage", "SaveImage", "PreviewImage"}.isdisjoint(nodes)
        assert nodes["KSampler"]["seed"] == 1234
        assert nodes["Krea2AnyglesLoadLoRA"]["lora_name"] == lora
        lora_id, model_port = nodes["Krea2AnyglesLoadLoRA"]["model"]
        assert payload["prompt"][lora_id]["class_type"] == "LoraLoader"
        assert model_port == 0
        assert nodes["LoraLoader"]["lora_name"] == character_lora
        assert nodes["LoraLoader"]["strength_model"] == 0.65
    assert camera_inputs == [45, 90, 135, 180, -135, -90]
    assert len(image_ids) == 1
    models.loras = []
    assert pov.available_models(models) is None


@pytest.mark.parametrize("reference_type", ["named", "canvas"])
@pytest.mark.parametrize("upscale", [False, True])
@pytest.mark.parametrize("fast_preview", [False, True])
def test_krea2_pose_studio_graph(reference_type, upscale, fast_preview):
    kind = WorkflowKind.refine if reference_type == "canvas" else WorkflowKind.generate
    models, template = _edit_work("general", kind)
    assert template.models and template.images and template.images.initial_image
    reference = Image.scale(template.images.initial_image, Extent(1024, 1280))
    identity = "KREA/krea2_identity_edit_v2.safetensors"
    models.loras = [identity, workflow.krea_live_lora]
    style = Style(Path("test.json"))
    style.checkpoints = [template.models.checkpoint]
    style.style_prompt = ""
    style.loras = [{"name": template.models.loras[0].name, "strength": 1.0}]
    original = ConditioningInput(
        "Place @subject on a rooftop." if reference_type == "named" else "A dancer on a rooftop.",
        edit_reference=reference_type == "canvas",
        pose_guide=PoseScene().render(Extent(384, 640)),
        pose_upscale=upscale,
    )
    if reference_type == "named":
        original.control.append(ControlInput(ControlMode.reference, reference, name="subject"))
    prepared = workflow.prepare_prompts(original, style, 1, Arch.krea2).conditioning
    work = workflow.prepare(
        kind,
        reference if original.edit_reference else reference.extent,
        prepared,
        style,
        1,
        models,
        FileLibrary.instance(),
        PerformanceSettings(),
        fast_preview=fast_preview,
    )
    graph = workflow.create(work, models)
    nodes = {
        n["class_type"]: (key, n["inputs"])
        for key, n in graph.root.items()
        if n["class_type"] != "Krea2EditGroundedEncode"
    }
    encoder = next(
        n["inputs"]
        for n in graph.root.values()
        if n["class_type"] == "Krea2EditGroundedEncode" and n["inputs"]["prompt"]
    )
    patch = nodes["Krea2EditModelPatch"][1]
    samplers = {
        key: n["inputs"] for key, n in graph.root.items() if n["class_type"] == "KSamplerAdvanced"
    }
    sampler = next(
        s for s in samplers.values() if s["model"] == [nodes["Krea2EditModelPatch"][0], 0]
    )
    assert nodes["LoraLoaderModelOnly"][1]["lora_name"] == identity
    if fast_preview:
        assert nodes["LoraLoader"][1]["lora_name"] == workflow.krea_live_lora
    else:
        assert "LoraLoader" not in nodes
    assert sampler["latent_image"] == patch["target_latent"] == [nodes["EmptySD3LatentImage"][0], 0]
    expected_sampler = ("euler", "simple", 2) if fast_preview else ("euler_ancestral", "beta", 8)
    assert (sampler["sampler_name"], sampler["scheduler"], sampler["steps"]) == expected_sampler
    assert patch["source_image"] == encoder["image"]
    assert encoder["prompt"].startswith("Draw character from image2.")
    assert "Use image1 only for the body pose" in encoder["prompt"]
    assert "Do not mirror the pose." in encoder["prompt"]
    assert "generate a high quality realistic color photograph" in encoder["prompt"]
    assert patch["ref_position_a"] == "aligned (trained)"
    assert patch["ref_position"] == "beside (right of target)"
    assert patch["ref_boost_a"] == 1.0 and patch["ref_boost"] == 4.0
    assert patch["source_image_b"] == encoder["image_b"] != encoder["image"]
    assert graph.root[encoder["image_b"][0]]["class_type"] != "ImageScale"
    assert len(samplers) == 1
    assert sampler["start_at_step"] == 0 and sampler["end_at_step"] == 10000
    assert nodes["EmptySD3LatentImage"][1]["width"] == (320 if fast_preview else 384)
    assert nodes["EmptySD3LatentImage"][1]["height"] == (512 if fast_preview else 640)
    assert ("ClownsharKSampler_Beta" in nodes) == (upscale and not fast_preview)
    if upscale and not fast_preview:
        scale_id, scale = nodes["LatentPixelScale"]
        assert scale["scale_factor"] == 1.5 and scale["scale_method"] == "lanczos"
        extra = nodes["ClownsharKSampler_Beta"][1]
        assert extra["model"] == sampler["model"] and extra["latent_image"] == [scale_id, 0]
        assert (extra["steps"], extra["denoise"], extra["seed"]) == (2, 0.3, 42)
        assert (extra["eta"], extra["sampler_name"], extra["scheduler"]) == (
            0.9,
            "exponential/res_2s",
            "bong_tangent",
        )
    if reference_type == "named":
        assert "Place image 2 on a rooftop" in encoder["prompt"]
        original.edit_reference = True
        with pytest.raises(ValueError, match="one of two image inputs"):
            workflow.prepare_prompts(original, style, 1, Arch.krea2)
        models.node_inputs = ComfyObjectInfo({"Krea2EditModelPatch": {}})
        with pytest.raises(ValueError, match="Update Krea 2 Edit nodes"):
            workflow.create(work, models)


def test_krea2_pose_requires_character_reference():
    cond = ConditioningInput("A dancer", pose_guide=PoseScene().render(Extent(64, 64)))
    with pytest.raises(ValueError, match="requires a character reference"):
        workflow.prepare_prompts(cond, Style(Path("test.json")), 1, Arch.krea2)


@pytest.mark.parametrize("edit_kind", ["identity", "general"])
def test_krea2_v2_edit(pytestconfig, edit_kind):
    if pytestconfig.getoption("--ci"):
        pytest.skip("Krea2 GPU inference is disabled on CI")
    url = os.environ.get("AI_DIFFUSION_TEST_URL", "http://127.0.0.1:8197").rstrip("/")
    models, work = _edit_work(edit_kind)
    models.node_inputs = ComfyObjectInfo(request(url + "/object_info"))
    graph = workflow.create(work, models)
    patch = next(n for n in graph.root.values() if n["class_type"] == "Krea2EditModelPatch")
    assert patch["inputs"]["ref_boost"] == (2.0 if edit_kind == "identity" else 4.0)
    assert "target_latent" in patch["inputs"]
    assert any(n["class_type"] == "Krea2EditGroundedEncode" for n in graph.root.values())
    _run_edit_graph(url, graph, f"krea2-{edit_kind}-v2", work)


@pytest.mark.parametrize("edit_kind", ["identity", "general"])
@pytest.mark.parametrize("view", ["right profile", "directly behind"])
@pytest.mark.parametrize("conditioning_mode", ["refine", "reference"])
def test_krea2_pov_experiment(pytestconfig, edit_kind, view, conditioning_mode):
    source = os.environ.get("AI_DIFFUSION_POV_SOURCE")
    if pytestconfig.getoption("--ci") or not source:
        pytest.skip("Set AI_DIFFUSION_POV_SOURCE to opt into the viewpoint experiment")
    url = os.environ.get("AI_DIFFUSION_TEST_URL", "http://127.0.0.1:8197").rstrip("/")
    kind = WorkflowKind.refine if conditioning_mode == "refine" else WorkflowKind.generate
    models, work = _edit_work(edit_kind, kind=kind)
    models.node_inputs = ComfyObjectInfo(request(url + "/object_info"))
    image = Image.load(source)
    work.images = _pov_images(image)
    assert work.conditioning
    work.conditioning.positive = (
        f"Rephotograph the reference scene from {view}. Move the camera around the stationary "
        "scene at the original height and distance. Keep the subject's identity, clothing, pose, "
        "object layout, environment, lighting and visual style. Show the parts now visible "
        "from the new camera position."
    )
    if kind is WorkflowKind.generate:
        work.conditioning.edit_reference = False
        work.conditioning.control = [
            ControlInput(ControlMode.reference, work.images.initial_image, strength=0.5)
        ]
    name = f"pov-krea2-{edit_kind}-{view.replace(' ', '-')}"
    if kind is WorkflowKind.generate:
        name += "-reference"
    _run_edit_graph(url, workflow.create(work, models), name, work, pov_result_dir)


@pytest.mark.parametrize("edit_kind", ["identity", "general"])
@pytest.mark.parametrize("azimuth", [90, 180])
@pytest.mark.parametrize("placement", ["aligned (trained)", "beside (right of target)"])
def test_krea2_pov_placement_experiment(pytestconfig, edit_kind, azimuth, placement):
    if pytestconfig.getoption("--ci") or os.getenv("AI_DIFFUSION_POV_PLACEMENT") != "1":
        pytest.skip("Set AI_DIFFUSION_POV_PLACEMENT=1 for the controlled camera experiment")
    url = os.environ.get("AI_DIFFUSION_TEST_URL", "http://127.0.0.1:8197").rstrip("/")
    models, work = _edit_work(edit_kind, kind=WorkflowKind.generate)
    models.node_inputs = ComfyObjectInfo(request(url + "/object_info"))
    assert work.conditioning and work.sampling
    work.images = _pov_images(Image.load(image_dir / "adobe_stock.jpg"), 768 * 512)
    relaxed = os.getenv("AI_DIFFUSION_POV_RELAXED") == "1"
    work.conditioning.edit_reference = False
    work.conditioning.control = [
        ControlInput(
            ControlMode.reference, work.images.initial_image, strength=0.5 if relaxed else 1
        )
    ]
    if relaxed:
        viewpoint = (
            "The short edge of the countertop recedes in perspective. A side-on view shows "
            "her nose in silhouette and her ponytail behind her head."
            if azimuth == 90
            else "Her back and ponytail are in the foreground. The counter and its vegetables "
            "are visible beyond her shoulders, across the kitchen."
        )
        work.conditioning.positive = (
            f"A candid photograph of the same kitchen and the same woman cutting carrots. "
            f"{viewpoint} She wears a charcoal cardigan over a grey shirt and holds the "
            "red-handled knife. Same pose, kitchen furniture and natural window light."
        )
    else:
        direction = (
            "right-side profile, 90 degrees around the counter, with only one eye visible"
            if azimuth == 90
            else "directly behind the woman, 180 degrees around the counter, with her face hidden"
        )
        work.conditioning.positive = (
            f"Rephotograph the same kitchen from the {direction}. Move the camera around the "
            "stationary woman and counter at the same height and distance. Keep her looking down "
            "and cutting carrots with a red-handled knife. Preserve her ponytail, grey shirt and "
            "dark cardigan, the positions of the windows, cabinets, counter and vegetables, and "
            "the natural daylight. Show the counter and kitchen from the new perspective."
        )
    work.sampling.seed = int(os.getenv("AI_DIFFUSION_POV_SEED", "1234"))
    graph = workflow.create(work, models)
    patch = next(n for n in graph.root.values() if n["class_type"] == "Krea2EditModelPatch")
    patch["inputs"]["ref_position"] = placement
    name = f"pov-placement-{edit_kind}-{azimuth}-{placement.split()[0]}-{work.sampling.seed}"
    if relaxed:
        name += "-relaxed"
    _run_edit_graph(url, graph, name, work, pov_result_dir)


def _pov_images(image: Image, pixel_count=512 * 512):
    extent = image.extent.scale_to_pixel_count(pixel_count).multiple_of(16)
    images = ImageInput.from_extent(extent)
    images.initial_image = Image.scale(image, extent)
    return images


@pytest.mark.parametrize("start_step", [4, 10])
def test_moss_pov_experiment(pytestconfig, start_step):
    source = os.environ.get("AI_DIFFUSION_POV_SOURCE")
    url = os.environ.get("AI_DIFFUSION_MOSS_TEST_URL")
    if pytestconfig.getoption("--ci") or not source or not url:
        pytest.skip("Set AI_DIFFUSION_POV_SOURCE and AI_DIFFUSION_MOSS_TEST_URL for MOSS")
    url = url.rstrip("/")
    info = request(url + "/object_info")

    def installed(node, field, fragment):
        names = info[node]["input"]["required"][field][0]
        match = next((name for name in names if fragment in name.lower()), None)
        if match is None:
            pytest.fail(f"{node}: no installed {field} matching {fragment}")
        return match

    checkpoint = installed("UNETLoader", "unet_name", "moss_image_sft")
    models = ClientModels()
    models.node_inputs = ComfyObjectInfo(info)
    models.checkpoints[checkpoint] = CheckpointInfo(checkpoint, Arch.moss, FileFormat.diffusion)
    models.resources = {
        resource_id(ResourceKind.text_encoder, Arch.moss, "qwen_3.5_9b"): installed(
            "CLIPLoader", "clip_name", "qwen3.5_9b"
        ),
        resource_id(ResourceKind.vae, Arch.moss, "default"): installed(
            "VAELoader", "vae_name", "flux2-vae.safetensors"
        ),
    }
    work = WorkflowInput(
        WorkflowKind.refine,
        models=CheckpointInput(checkpoint, Arch.moss),
        images=_pov_images(Image.load(source)),
        conditioning=ConditioningInput(
            "A photograph of the same stationary scene from its right side, a 90 degree "
            "side view at the original camera height and distance. Keep the same subject, "
            "outfit, pose, surroundings and lighting."
        ),
        sampling=SamplingInput("euler", "simple", 3.0, 20, start_step=start_step, seed=1234),
    )
    _run_edit_graph(
        url, workflow.create(work, models), f"pov-moss-start-{start_step}", work, pov_result_dir
    )


def _run_edit_graph(url, graph, name, work, output_dir=result_dir):
    # Use standard image transport so this test only needs the Krea2 node pack.
    for node in graph.root.values():
        if node["class_type"] == "ETN_LoadImageCache":
            data = graph.image_data[node["inputs"]["id"]]
            upload = requests.post(
                url + "/upload/image",
                files={"image": (f"{name}-source.webp", data, "image/webp")},
                data={"overwrite": "true"},
                timeout=30,
            )
            upload.raise_for_status()
            node.update(class_type="LoadImage", inputs={"image": upload.json()["name"]})
        elif node["class_type"] == "ETN_SaveImageCache":
            node.update(
                class_type="SaveImage",
                inputs={
                    "images": node["inputs"]["images"],
                    "filename_prefix": name,
                },
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{name}.json").write_text(json.dumps(graph.root, indent=2))
    try:
        submitted = request(url + "/prompt", {"prompt": graph.root})
    except HTTPError as error:
        pytest.fail(error.read().decode())
    prompt_id = submitted["prompt_id"]
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        history = request(url + "/history/" + prompt_id)
        if entry := history.get(prompt_id):
            assert entry["status"]["status_str"] == "success", entry["status"]
            output = next(o for o in entry["outputs"].values() if "images" in o)["images"][0]
            with urlopen(url + "/view?" + urlencode(output), timeout=30) as response:
                data = response.read()
            path = output_dir / f"{name}.png"
            path.write_bytes(data)
            image = Image.load(path)
            assert work.images is not None and work.images.initial_image is not None
            assert image.extent == work.images.initial_image.extent
            assert image.to_numpy_format() != work.images.initial_image.to_numpy_format()
            return
        time.sleep(0.5)
    pytest.fail(f"{name} timed out: {prompt_id}; inspect the server before rerunning")
