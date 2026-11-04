import json
import os
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest
import requests

from ai_diffusion.backend import workflow
from ai_diffusion.backend.api import (
    CheckpointInput,
    ConditioningInput,
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
from ai_diffusion.backend.resources import Arch, ResourceKind, resource_id
from ai_diffusion.files import FileFormat
from ai_diffusion.image import Bounds, Extent, Image
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
    assert any(n["inputs"].get("model") == [patch_id, 0] for n in graph.root.values())
    grounded = [n for n in graph.root.values() if n["class_type"] == "Krea2EditGroundedEncode"]
    assert len(grounded) == (2 if cfg > 1 else 1)
    assert all(n["inputs"]["image"] == patch["inputs"]["source_image"] for n in grounded)


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
