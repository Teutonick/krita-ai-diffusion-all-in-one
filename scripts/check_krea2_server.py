import argparse
import json
import struct
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request(url: str, data: dict | None = None):
    payload = json.dumps(data).encode() if data is not None else None
    with urlopen(
        Request(url, payload, {"Content-Type": "application/json"}), timeout=15
    ) as response:
        return json.load(response)


def check(url: str, smoke: bool):
    info = request(url + "/object_info")
    failures = []
    for name, required in {
        "Krea2EditModelPatch": {
            "source_latent",
            "source_image",
            "vae",
            "target_latent",
            "fit_mode",
            "ref_boost",
            "ref_boost_a",
            "ref_position",
            "ref_position_a",
        },
        "Krea2EditGroundedEncode": {"clip", "prompt", "image", "image_b", "grounding_px"},
    }.items():
        inputs = info.get(name, {}).get("input", {})
        supported = set(inputs.get("required", {})) | set(inputs.get("optional", {}))
        missing = sorted(required - supported)
        if missing:
            failures.append(f"{name}: missing inputs {', '.join(missing)}")

    def choices(node, field):
        return info.get(node, {}).get("input", {}).get("required", {}).get(field, [[]])[0]

    loras = choices("LoraLoader", "lora_name")
    for filename in ("krea2_identity_edit_v2.safetensors", "krea2_general_edit_v2.safetensors"):
        if not any(Path(name.replace("\\", "/")).name == filename for name in loras):
            failures.append(f"Missing LoRA: {filename}")
    if not any("qwen3vl_4b" in name.lower() for name in choices("CLIPLoader", "clip_name")):
        failures.append("Missing Qwen3-VL 4B encoder")
    if not any("krea2" in name.lower() for name in choices("UNETLoader", "unet_name")):
        failures.append("Missing Krea2 diffusion model")
    if not any("qwen_image_vae" in name.lower() for name in choices("VAELoader", "vae_name")):
        failures.append("Missing Qwen Image VAE")

    result = {"url": url, "krea2_v2_ready": not failures, "failures": failures}
    if smoke:
        result["image_pipeline_smoke"] = run_smoke(url)
    return result


def run_smoke(url: str):
    graph = {
        "1": {
            "class_type": "EmptyImage",
            "inputs": {
                "width": 64,
                "height": 64,
                "batch_size": 1,
                "color": 0x336699,
            },
        },
        "2": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["1", 0],
                "upscale_method": "nearest-exact",
                "width": 32,
                "height": 48,
                "crop": "disabled",
            },
        },
        "3": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["2", 0],
                "filename_prefix": "production-smoke",
            },
        },
    }
    submitted = request(url + "/prompt", {"prompt": graph})
    prompt_id = submitted["prompt_id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        history = request(url + "/history/" + prompt_id)
        if entry := history.get(prompt_id):
            if entry["status"]["status_str"] != "success":
                raise RuntimeError(f"ComfyUI smoke failed: {entry['status']}")
            image = entry["outputs"]["3"]["images"][0]
            with urlopen(url + "/view?" + urlencode(image), timeout=15) as response:
                png = response.read()
            if png[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", png[16:24]) != (32, 48):
                raise RuntimeError("ComfyUI returned an invalid image or dimensions")
            return {"passed": True, "prompt_id": prompt_id, "width": 32, "height": 48}
        time.sleep(0.25)
    raise TimeoutError("ComfyUI smoke timed out")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check Krea2 V2 dependencies without loading models"
    )
    parser.add_argument("--url", default="http://127.0.0.1:8197")
    parser.add_argument(
        "--smoke", action="store_true", help="Execute an image-only job; no diffusion"
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = check(args.url.rstrip("/"), args.smoke)
    output = json.dumps(report, indent=2) + "\n"
    print(output, end="")
    if args.report:
        args.report.write_text(output, encoding="utf-8")
    raise SystemExit(0 if report["krea2_v2_ready"] else 1)
