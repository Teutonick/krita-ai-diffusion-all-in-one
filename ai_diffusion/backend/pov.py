from pathlib import PurePosixPath

from .api import CameraView
from .client import ClientModels
from .resources import Arch, ResourceId, ResourceKind

pov_component = "Make POVs"
pov_lora = "krea2_anygles_rank32.safetensors"
pov_dino_revision = "6876159a11b4df116f30f667f8c9888617df0751"
pov_dino_sha256 = "8f3ba3a5e4f017c4ae209cf3052ac3ffae714bc8308d1e541db7c6050294ece2"
_sam_base = (
    "https://huggingface.co/Blendcap/sam-3d-body/resolve/fa738e386f37c7c00ed3befb46cf995f4ed3131c/"
)
_anygles_base = "https://huggingface.co/yijunwang2/krea2-anygles/resolve/87a0f39574ecfdedaf26e84e19fcbd7379ba0897/"
pov_assets = (
    (
        "krita_pov/model.ckpt",
        _sam_base + "model.ckpt",
        "b5a2f9d305dd02626b967aa2e86021fba07065df66ce7a7e00ffb9664f150abf",
    ),
    (
        "krita_pov/assets/mhr_model.pt",
        _sam_base + "assets/mhr_model.pt",
        "352e271a6c42729c68554ceaea0c955e866970160c31e35506d782dc0f7377bc",
    ),
    (
        "krita_pov/model_config.yaml",
        _sam_base + "model_config.yaml",
        "1012fc3f39cb5e90e3f8fbadf7bded31604bfafdce0321d17a7c1a2d3f08b88d",
    ),
    (
        "krita_pov/SAM_LICENSE",
        _sam_base + "LICENSE",
        "b3a5a0e2d973ab80e6610ccf1cffc40756050d0ace3cd4fec879b3ec290b2e9b",
    ),
    (
        "krita_pov/moge.pt",
        "https://huggingface.co/Ruicheng/moge-2-vitl-normal/resolve/cb0e8bbd6b1e243589717c78e750b1ba4c093acf/model.pt",
        "280741fd09bc3f403ccff9967784c2a391b52d2c0742ae3efdb21d9f90cc1a01",
    ),
    (
        "krita_pov/detector.pth",
        "https://download.pytorch.org/models/ssdlite320_mobilenet_v3_large_coco-a79551df.pth",
        "a79551df90c79834bcd3bb3845ef9d966b5449a3a9b2833ae8404778ca5d65d2",
    ),
    (
        "loras/" + pov_lora,
        _anygles_base + pov_lora,
        "248a2a6523da416bbde1846b9192c5f94b2cfe0192a0d5ba4b65b83085631ce9",
    ),
    (
        "krita_pov/Anygles-LICENSE.pdf",
        _anygles_base + "LICENSE.pdf",
        "b82a2805162bde714a4eb27b9063c4fc3345d08a30be055134a6160e5430ba74",
    ),
    (
        "krita_pov/Anygles-NOTICE",
        _anygles_base + "NOTICE",
        "7fed6a793a44277dbaafa80a782247f267dee23aff5a7ed1de0b7a643e37f175",
    ),
)
pov_nodes = (
    "KritaPOVGeometry",
    "KritaPOVNormal",
    "Krea2AnyglesEncode",
    "Krea2AnyglesLoadLoRA",
    "Krea2AnyglesModelPatch",
)
pov_views = (
    ("Front-right", CameraView(45)),
    ("Right", CameraView(90)),
    ("Rear-right", CameraView(135)),
    ("Rear", CameraView(180)),
    ("Rear-left", CameraView(-135)),
    ("Left", CameraView(-90)),
)
pov_vertical_views = (
    ("Front from below", CameraView(0, -60)),
    ("Front from above", CameraView(0, 60)),
    ("Rear from below", CameraView(180, -60)),
    ("Rear", CameraView(180)),
    ("Rear from above", CameraView(180, 60)),
)


def _basename(name: str):
    return PurePosixPath(name.replace("\\", "/")).name.lower()


def h3_checkpoint(models: ClientModels):
    if "MiniMaxH3ImageConditioning" not in models.node_inputs:
        return None
    h3 = models.for_arch(Arch.minimax_h3_image)
    if not models.find(ResourceId(ResourceKind.vae, Arch.minimax_h3_image, "default")):
        return None
    if not (h3.text_encoder.find("h3_heretic") or h3.text_encoder.find("h3_qwen3vl")):
        return None
    return next(
        (
            name
            for name in models.checkpoints
            if _basename(name) == "minimax_h3_image_pruned_w4a8.safetensors"
        ),
        None,
    )


def available_models(models: ClientModels):
    if not all(node in models.node_inputs for node in pov_nodes):
        return None
    if "subject_context" not in (models.node_inputs.inputs("KritaPOVNormal", "optional") or {}):
        return None
    available = {_basename(name): name for name in models.checkpoints}
    checkpoint = next(
        (
            available[name]
            for name in (
                "krea2_turbo_int8_convrot.safetensors",
                "krea2_turbo_fp8_scaled.safetensors",
                "krea2_turbo_bf16.safetensors",
            )
            if name in available
        ),
        None,
    )
    lora = next((name for name in models.loras if _basename(name) == pov_lora), None)
    krea = models.for_arch(Arch.krea2)
    if checkpoint and lora and krea.has_te_vae:
        return checkpoint, lora
    return None
