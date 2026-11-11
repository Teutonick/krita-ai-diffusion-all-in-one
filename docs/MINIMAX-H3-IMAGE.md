# MiniMax H3 Image

Managed Server installs [ComfyUI v0.45.0](https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.45.0), which includes native H3 Image support. If Krita reports **Upgrade required**, run **Upgrade** in the connection settings. If you use an external server, update it separately. For pDMD the server also needs `MiniMaxH3SigmaShift`.

There is no separate H3 Workload checkbox. The preset becomes available when the connected server reports the checkpoint, a compatible text encoder and VAE, and the H3 Image node. After adding weights, restart that ComfyUI instance if needed, then refresh the connection in Krita. The Style Presets page shows what the connected server is missing.

In **Configure Image Diffusion → Connection → Individual Packages → MiniMax H3 Image**, choose a checkpoint, the H3 Image VAE and one Qwen3-VL encoder. For a separate server, place the files in its corresponding model directories:

| Component | Directory | Source |
| --- | --- | --- |
| Standard checkpoint: INT8 ConvRot, W4A8 or BF16 | `models/diffusion_models` | [Comfy-Org H3 Image](https://huggingface.co/Comfy-Org/MiniMax-H3-Image/tree/main/diffusion_models) |
| pDMD two-step checkpoint: merged BF16, 40.2 GB | `models/diffusion_models` | [akhaliq pDMD](https://huggingface.co/akhaliq/minimax-h3-image-pdmd-2step/tree/main) |
| H3 Image VAE | `models/vae` | [Comfy-Org H3 Image VAE](https://huggingface.co/Comfy-Org/MiniMax-H3-Image/tree/main/vae) |
| Official Qwen3-VL 32B, or community Heretic INT8 ConvRot / NVFP4 | `models/text_encoders` | [Official](https://huggingface.co/Comfy-Org/MiniMax-H3-Image/tree/main/text_encoders), [Heretic INT8](https://huggingface.co/ethanfel/Qwen3-VL-32B-Ultra-Heretic-H3-ComfyUI-INT8-ConvRot), [Heretic NVFP4](https://huggingface.co/Momoking/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4) |

The plugin prefers a recognized Heretic encoder when installed and otherwise uses the official encoder. These are community variants originally packaged for H3 video; MiniMax documents that H3 Image uses the same encoder. Compare results with the official encoder if prompt following or reference fidelity changes. NVFP4 performance depends on the GPU and server build. Review the [MiniMax H3 Image license](https://huggingface.co/MiniMaxAI/MiniMax-H3-Image/blob/main/LICENSE) before downloading the model.

- **Standard (6 steps)** uses the official checkpoint schedule, Euler / simple, CFG 1. Use this preset for quality and baseline comparisons.
- **pDMD (2 steps, experimental)** uses the merged checkpoint and the author's flow shift (12). Switch back to Standard to turn off pDMD. The checkpoints are separate; the plugin does not apply a second copy of the pDMD LoRA.
- **Edit**: pick the visible canvas or a source layer and describe the change. Use `@reference` for additional pictures. For a local edit, make a Krita selection before submitting. The plugin passes the selection as a black-and-white guide and applies the result through that same mask. Pixels outside the selection remain on the original layer.
- Both presets start at roughly 4 MP internally and respect the performance pixel cap. To try a larger render, duplicate the style and raise Preferred Resolution and the pixel cap as your hardware permits. H3 uses fixed checkpoint schedules; the negative prompt and generic denoise strength are not used by this workflow.
