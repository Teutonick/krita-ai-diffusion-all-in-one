import json
from pathlib import Path

import pytest

from ai_diffusion.backend import pov, workflow
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
from ai_diffusion.image import Bounds, Extent, Image, Mask
from ai_diffusion.pose_studio import PoseScene
from ai_diffusion.settings import PerformanceSettings
from ai_diffusion.style import Style


@pytest.mark.parametrize("editing", [False, True])
def test_h3_live_uses_pdmd_on_selected_checkpoint(editing):
    arch = Arch.minimax_h3_image
    checkpoint = "minimax_h3_image_pruned_int8_convrot.safetensors"
    models = ClientModels()
    models.checkpoints[checkpoint] = CheckpointInfo(checkpoint, arch, FileFormat.diffusion)
    models.resources = {
        resource_id(ResourceKind.text_encoder, Arch.all, "h3_qwen3vl"): "official.safetensors",
        resource_id(ResourceKind.vae, arch, "default"): "h3_image_vae.safetensors",
    }
    models.node_inputs = ComfyObjectInfo({
        "MiniMaxH3ImageConditioning": {},
        "MiniMaxH3SigmaShift": {},
    })
    style = Style(Path("test-h3.json"))
    style.checkpoints = [checkpoint]
    assert not workflow.supports_live_preview(style, models, editing)
    models.loras = [workflow.h3_live_lora]
    assert workflow.supports_live_preview(style, models, editing)
    extent = Extent(1280, 960)
    canvas = Image.create(extent, 255) if editing else extent
    kind = WorkflowKind.refine if editing else WorkflowKind.generate
    for live in (True, False):
        cond = ConditioningInput(
            "A robot in <Picture 1>.",
            edit_reference=editing,
            control=[ControlInput(ControlMode.reference, Image.create(extent, 255))],
        )
        work = workflow.prepare(
            kind,
            canvas,
            cond,
            style,
            42,
            models,
            FileLibrary(FileCollection(), FileCollection()),
            PerformanceSettings(h3_live_resolution=768),
            fast_preview=live,
        )
        nodes = {n["class_type"]: n["inputs"] for n in workflow.create(work, models).root.values()}
        assert work.models and work.models.checkpoint == checkpoint
        assert nodes["KSampler"]["steps"] == (2 if live else 6)
        assert nodes["MiniMaxH3ImageConditioning"]["width"] == (768 if live else 1280)
        assert ("images.image_1" in nodes["MiniMaxH3ImageConditioning"]) is editing
        assert ("MiniMaxH3SigmaShift" in nodes) is live
        if live:
            assert nodes["LoraLoaderModelOnly"]["lora_name"] == workflow.h3_live_lora
            assert "ETN_SaveImageCache" in nodes
            assert {"LoadImage", "SaveImage", "PreviewImage"}.isdisjoint(nodes)
        else:
            assert "LoraLoaderModelOnly" not in nodes


@pytest.mark.parametrize("with_loras", [False, True])
def test_h3_make_povs(with_loras):
    arch = Arch.minimax_h3_image
    checkpoint = "minimax_h3_image_pruned_w4a8.safetensors"
    models = ClientModels()
    models.checkpoints[checkpoint] = CheckpointInfo(checkpoint, arch, FileFormat.diffusion)
    models.resources = {
        resource_id(ResourceKind.text_encoder, Arch.all, "h3_qwen3vl"): "official.safetensors",
        resource_id(ResourceKind.vae, arch, "default"): "h3_image_vae.safetensors",
    }
    assert pov.h3_checkpoint(models) is None
    models.node_inputs = ComfyObjectInfo({"MiniMaxH3ImageConditioning": {}})
    assert pov.h3_checkpoint(models) == checkpoint
    files = FileLibrary(FileCollection(), FileCollection())
    style = Style(Path("test-h3.json"))
    prompt = "Porcelain android."
    expected_loras = {}
    if with_loras:
        expected_loras = {"style.safetensors": 0.6, "tagged.safetensors": 0.4}
        models.loras = list(expected_loras)
        files.loras.extend([File.remote(name) for name in models.loras])
        style.loras = [
            {"name": "style.safetensors", "strength": 0.6},
            {"name": "disabled.safetensors", "strength": 1.0, "enabled": False},
        ]
        prompt += " <lora:style:0.9> <lora:tagged:0.4>"
    description, loras = workflow.prepare_h3_pov_prompt(prompt, 1234, style, models, files)
    extent = Extent(96, 64)
    images = ImageInput.from_extent(extent)
    images.initial_image = Image.create(extent, 0xFF193246)
    prompts = set()
    for _, view in (*pov.pov_views, *pov.pov_vertical_views):
        work = WorkflowInput(
            WorkflowKind.pov,
            images=images,
            models=CheckpointInput(checkpoint, arch, loras=loras),
            conditioning=ConditioningInput(description, "Changed costume."),
            sampling=SamplingInput("euler", "simple", 1.0, 6, seed=1234),
            camera_view=view,
        )
        graph = workflow.create(work, models)
        nodes = {node["class_type"]: node["inputs"] for node in graph.root.values()}
        assert "KritaPOVGeometry" not in nodes
        applied = {
            node["inputs"]["lora_name"]: node["inputs"]["strength_model"]
            for node in graph.root.values()
            if node["class_type"] == "LoraLoader"
        }
        assert applied == expected_loras
        cond = nodes["MiniMaxH3ImageConditioning"]
        assert [key for key in cond if key.startswith("images.")] == ["images.image_0"]
        assert "Porcelain android." in cond["prompt"] and "Changed costume." in cond["prompt"]
        assert cond["prompt"].startswith("<sks> ")
        assert "Show the existing background from the new camera position" in cond["prompt"]
        if view.azimuth == 180:
            assert cond["prompt"].startswith("<sks> back view ")
        if view.elevation == -60:
            assert "low-angle shot" in cond["prompt"] and "60 degrees upward" in cond["prompt"]
        assert "<lora:" not in cond["prompt"]
        assert nodes["KSampler"]["seed"] == 1234
        assert nodes["KSampler"]["steps"] == 6
        prompts.add(cond["prompt"])
    assert len(prompts) == 10  # Both series include the 180-degree eye-level view.


@pytest.mark.parametrize(
    "kind, expected_refs",
    [(WorkflowKind.generate, 0), (WorkflowKind.refine, 2), (WorkflowKind.refine_region, 3)],
)
@pytest.mark.parametrize("turbo", [False, True])
@pytest.mark.parametrize("pose", [False, True])
def test_h3_image_graph(kind, expected_refs, turbo, pose):
    arch = Arch.minimax_h3_image
    checkpoint = (
        "minimax_h3_image_pdmd_2step_bf16.safetensors"
        if turbo
        else "minimax_h3_image_pruned_int8_convrot.safetensors"
    )
    models = ClientModels()
    models.checkpoints[checkpoint] = CheckpointInfo(checkpoint, arch, FileFormat.diffusion)
    models.resources = {
        resource_id(ResourceKind.text_encoder, Arch.all, "h3_qwen3vl"): "official.safetensors",
        resource_id(ResourceKind.text_encoder, Arch.all, "h3_heretic"): "heretic.safetensors",
        resource_id(ResourceKind.vae, arch, "default"): "h3_image_vae.safetensors",
    }
    extent = Extent(96, 64)
    bounds = Bounds(12, 10, 32, 20)
    images = ImageInput.from_extent(extent)
    cond = ConditioningInput("Paint the chair blue.")
    work = WorkflowInput(
        kind,
        images=images,
        models=CheckpointInput(checkpoint, arch),
        conditioning=cond,
        sampling=SamplingInput("dpmpp_2m", "normal", 7.0, 20, seed=42),
    )
    if kind is WorkflowKind.refine:
        assert work.models is not None
        work.models.loras = [LoraInput("minimax/robot-h3.safetensors", 0.5)]
    if kind is not WorkflowKind.generate:
        images.initial_image = Image.create(extent, 0xFF193246)
        cond.control.append(ControlInput(ControlMode.reference, Image.create(extent, 255)))
    if kind is WorkflowKind.refine_region:
        images.hires_mask = Mask.rectangle(bounds, Bounds.from_extent(extent)).to_image(extent)
        work.inpaint = InpaintParams(InpaintMode.custom, bounds)
    if pose:
        cond.edit_reference = images.initial_image is not None
        cond.pose_guide = PoseScene().render(extent)

    graph = workflow.create(work, models)
    payload = json.loads(json.dumps({"prompt": graph.root}))
    nodes = {n["class_type"]: (key, n["inputs"]) for key, n in payload["prompt"].items()}
    conditioning_id, conditioning = nodes["MiniMaxH3ImageConditioning"]
    refs = [key for key in conditioning if key.startswith("images.")]
    assert refs == [f"images.image_{n}" for n in range(expected_refs + int(pose))]
    assert "Paint the chair blue." in conditioning["prompt"]
    if pose:
        guide_index = 1 if kind is WorkflowKind.generate else 3
        assert f"Use <Picture {guide_index}> only for pose and camera" in conditioning["prompt"]
        blur_id, blur = nodes["ImageBlur"]
        assert (blur["blur_radius"], blur["sigma"]) == (5, 5.0)
        assert conditioning[f"images.image_{guide_index - 1}"] == [blur_id, 0]
        if kind is not WorkflowKind.generate:
            assert "the single character in <Picture 1>" in conditioning["prompt"]
            assert conditioning["images.image_0"] != [blur_id, 0]
            assert not conditioning["prompt"].startswith("Edit <Picture 1>. ")
    model_link = [nodes["UNETLoader"][0], 0]
    clip_link = [nodes["CLIPLoader"][0], 0]
    if kind is WorkflowKind.refine:
        lora_id, lora = nodes["LoraLoader"]
        assert lora["model"] == model_link
        assert lora["lora_name"] == "minimax/robot-h3.safetensors"
        assert lora["strength_model"] == 0.5
        model_link, clip_link = [lora_id, 0], [lora_id, 1]
    assert conditioning["clip"] == clip_link
    assert nodes["CLIPLoader"][1]["clip_name"] == (
        "official.safetensors" if pose else "heretic.safetensors"
    )
    sampler_id, sampler = nodes["KSampler"]
    assert sampler["latent_image"] == [conditioning_id, 1]
    assert sampler["negative"] == [nodes["ConditioningZeroOut"][0] if pose else conditioning_id, 0]
    assert sampler["steps"] == (2 if turbo else 6)
    assert (sampler["sampler_name"], sampler["scheduler"], sampler["cfg"]) == (
        "euler",
        "simple",
        1.0,
    )
    if turbo:
        assert sampler["model"] == [nodes["MiniMaxH3SigmaShift"][0], 0]
        assert nodes["MiniMaxH3SigmaShift"][1]["shift_video"] == 12.0
        assert nodes["MiniMaxH3SigmaShift"][1]["model"] == model_link
    else:
        assert "MiniMaxH3SigmaShift" not in nodes
        assert sampler["model"] == model_link
    assert nodes["VAEDecode"][1]["samples"] == [sampler_id, 0]
    assert not {"Krea2EditModelPatch", "Krea2EditGroundedEncode"} & nodes.keys()
    if kind is WorkflowKind.refine_region:
        mask_index = 3 + int(pose)
        assert f"<Picture {mask_index}> are white" in conditioning["prompt"]
        assert conditioning[f"images.image_{mask_index - 1}"] == [nodes["MaskToImage"][0], 0]
        assert nodes["ETN_ApplyMaskToImage"][1]["mask"] == [nodes["CropMask"][0], 0]
    else:
        assert "ETN_ApplyMaskToImage" not in nodes

    models.node_inputs = ComfyObjectInfo({"KSampler": {}})
    with pytest.raises(ValueError, match="MiniMaxH3ImageConditioning"):
        workflow.create(work, models)
