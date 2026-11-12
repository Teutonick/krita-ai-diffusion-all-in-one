import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest
import requests

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
from ai_diffusion.files import FileFormat, FileLibrary
from ai_diffusion.image import Bounds, Extent, Image
from ai_diffusion.pose_studio import PoseScene
from ai_diffusion.settings import PerformanceSettings
from ai_diffusion.style import Style
from scripts.check_krea2_server import request

from .config import image_dir, result_dir


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


@pytest.mark.parametrize("reference_type", ["named", "canvas"])
@pytest.mark.parametrize("upscale", [False, True])
def test_krea2_pose_studio_graph(reference_type, upscale):
    kind = WorkflowKind.refine if reference_type == "canvas" else WorkflowKind.generate
    models, template = _edit_work("general", kind)
    assert template.models and template.images and template.images.initial_image
    reference = Image.scale(template.images.initial_image, Extent(1024, 1280))
    identity = "KREA/krea2_identity_edit_v2.safetensors"
    models.loras = [identity]
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
    assert "LoraLoader" not in nodes
    assert sampler["latent_image"] == patch["target_latent"] == [nodes["EmptySD3LatentImage"][0], 0]
    assert (sampler["sampler_name"], sampler["scheduler"], sampler["steps"]) == (
        "euler_ancestral",
        "beta",
        8,
    )
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
    assert nodes["EmptySD3LatentImage"][1]["width"] == 384
    assert nodes["EmptySD3LatentImage"][1]["height"] == 640
    assert ("ClownsharKSampler_Beta" in nodes) == upscale
    if upscale:
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
    # Use standard image transport so this test only needs the Krea2 node pack.
    for node in graph.root.values():
        if node["class_type"] == "ETN_LoadImageCache":
            data = graph.image_data[node["inputs"]["id"]]
            upload = requests.post(
                url + "/upload/image",
                files={"image": (f"krea2-{edit_kind}-source.webp", data, "image/webp")},
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
                    "filename_prefix": f"krea2-{edit_kind}-v2",
                },
            )
    (result_dir / f"krea2-{edit_kind}-v2.json").write_text(json.dumps(graph.root, indent=2))
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
            path = result_dir / f"krea2-{edit_kind}-v2.png"
            path.write_bytes(data)
            image = Image.load(path)
            assert work.images is not None and work.images.initial_image is not None
            assert image.extent == work.images.initial_image.extent
            assert image.to_numpy_format() != work.images.initial_image.to_numpy_format()
            return
        time.sleep(0.5)
    pytest.fail(f"Krea2 job timed out: {prompt_id}; inspect the server before rerunning")
