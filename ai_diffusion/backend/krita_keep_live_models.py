"""Optional ComfyUI node installed by Managed Server for Krea 2 Live."""

import logging


class KritaKeepLiveModelsLoaded:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "clip": ("CLIP",)}}

    RETURN_TYPES = ("MODEL", "CLIP")
    FUNCTION = "load"
    CATEGORY = "Krita/Experimental"

    def load(self, model, clip):
        from comfy import model_management as mm  # pyright: ignore[reportMissingImports]

        device = model.load_device
        if device.type != "cuda" or clip.patcher.load_device != device:
            raise RuntimeError("Krita Live VRAM requires both models on the same CUDA device")
        reserve = max(2 * 1024**3, mm.minimum_inference_memory())
        size = model.model_size() + clip.patcher.model_size()
        if size + reserve > mm.get_total_memory(device):
            raise RuntimeError("Krita Live VRAM has insufficient capacity for both models")

        # Dynamic patchers stage weights on demand. Use standard patchers for this graph.
        model = model.clone(disable_dynamic=True)
        clip = clip.clone(disable_dynamic=True)
        clip.cond_stage_model = clip.patcher.model
        mm.load_models_gpu([model, clip.patcher], memory_required=reserve, force_full_load=True)
        if any(patcher.loaded_size() < patcher.model_size() for patcher in (model, clip.patcher)):
            raise RuntimeError("Krita Live VRAM could not load both models completely")
        logging.getLogger(__name__).info("[Krita Live VRAM] Krea 2 and Qwen3-VL loaded together")
        return model, clip


NODE_CLASS_MAPPINGS = {"KritaKeepLiveModelsLoaded": KritaKeepLiveModelsLoaded}
