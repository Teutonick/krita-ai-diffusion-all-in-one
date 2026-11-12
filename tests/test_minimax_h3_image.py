import json

import pytest

from ai_diffusion.backend import workflow
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
from ai_diffusion.files import FileFormat
from ai_diffusion.image import Bounds, Extent, Image, Mask
from ai_diffusion.pose_studio import PoseScene


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
