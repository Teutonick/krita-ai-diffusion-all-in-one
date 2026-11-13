# 1.53.0-all-in-one.36 — krita-ai-diffusion-all-in-one

Restores automatic opening of the default browser when Pose Studio runs
without Qt WebEngine.

Pose Library can browse VNCCS Main and General Poses on demand. The local
library remains the default; remote catalogs and previews are not saved to disk.

Hides LoRAs and checkpoints with unknown or adult ratings from the initial SFW
list, including cached rows with stale local preview ratings. Dictation uses
the locked temporary media session, and Pose Studio uses no-store responses
and an off-the-record embedded browser. See THIRD-PARTY-NOTICES.md for Whisper.

Fixes the prompt toolbar layout: the translation button and negative prompt
warning stay on the right whether the microphone is visible or hidden.

Adds local voice dictation on Windows x64 in **Settings → Integrations → Voice
Dictation**. Use the microphone in image and video prompt fields and in Prompt AI
instruction dialogs. The multilingual Whisper model downloads on first enable,
runs on the CPU, and releases memory after each transcription.

- LoRA and model browsers default to SFW, with SFW-only, NSFW-only and all-rating filters. Unrated previews appear only in All.

- The in-plugin updater checks this fork’s GitHub Releases and installs verified plugin ZIPs. Restart Krita manually to finish.

- Krea 2 Pose Studio keeps the mannequin aligned and places the character reference beside the canvas, improving pose transfer in the tested case.
- README highlights Pose Editor and the third-party notices document the editor, rig, server nodes and their separate license terms.

- MiniMax H3 Pose Studio separates character identity from pose and camera guidance, blurs the pose render as in the reference workflow, and uses the native zero-based image slots.
- Krea 2 Pose Studio passes the original character reference to the edit nodes and preserves the internal image-role instructions when translating the user prompt.
- Pose Library saves reusable poses and previews locally across editor sessions.

- Krea 2 Pose Studio supplies image roles and screen-side pose instructions automatically.

- Pose Studio attempts to close its browser tab after successfully sending the pose to Krita.

- A single optional VNCCS Pose Studio checkbox installs the editor, Impact Pack and RES4LYF together.
- Pose Studio releases its WebGL editor and workers after applying or cancelling, and opens at most one external browser tab per session.
- Krea 2 Pose Studio follows the FoxFurEssence reference-based workflow, without a generated appearance draft. The original upscale pass is available via two optional server components.
- VNCCS Pose Studio assets are now an optional download under Managed Server > Additional components. Saved renders remain usable without the editor download.
- Pose Studio now uses the original VNCCS editor and MakeHuman rig, with individual fingers, camera controls and import of VNCCS pose data from ComfyUI workflows.
- Krea 2 Pose Studio generates a separate appearance draft when no character reference is provided. With either kind of reference, the pose is aligned to the target and the character reference is placed beside it to reduce competition from the original pose.
- Pose Studio controls now share the Strength row. Generation and Edit workflows are unchanged when the pose is off or no scene has been saved.
- Krea 2 Pose Studio now starts from a fresh latent and uses Identity Edit V2, with the pose in image A and the optional character reference in image B. The mannequin has a shaded human silhouette and a black background.
- Added optional Pose Studio for Krea 2 and MiniMax H3 Image. Pose the mannequin and frame the shot in Krita, then generate with or without a separate character reference.
- Consecutive runs with the same prompt and settings now share a history row even when they take different amounts of time.
- Added a MiniMax H3 filter in the LoRA browser. Video LoRAs are experimental on H3 Image.
- Fixed JSON submission of MiniMax H3 Image jobs and a false checkpoint warning for supported H3 styles.
- Managed Server now upgrades to ComfyUI v0.45.0 with native MiniMax H3 Image support.
- MiniMax H3 Image style warnings now identify missing server support or model files.
- Added plain-language guidance to the MiniMax H3 Image package list: a starting setup, smaller downloads, and a two-step draft option.
- Added MiniMax H3 Image generation, source and selection edits, and separate Standard (6 steps) and experimental pDMD (2 steps) presets. Requires a ComfyUI server with native H3 Image support.
- Animation prompts can be modified in their own window and suggest subtle motion for relevant scene elements.
- Added a subtle live VRAM usage indicator to the queue button.
- Animation prompt for image describes the canvas and opens a copyable image-to-video prompt in the official MiniMax H3 I2VA syntax.
- Consecutive matching generations are grouped together in history.
- Modify with instruction focuses the text field when opened.
- AI commands now use the Ollama model selected in settings, including image description.
- Favorite badges retain thumbnail size and share a consistent appearance across styles and LoRAs.
- LoRA browsing scrolls in smaller steps.
- New all-in-one logo for the plugin headers.
- LoRA Add to Prompt now targets the active Generate/Edit prompt.
- Scan server refreshes existing LoRAs and retrieves missing triggers and base-model data by CivitAI hash. Browser metadata caches remain in RAM only.
- Base-model filtering now excludes unknown and other architectures; Any still shows all local files.


An independent community build by **Teutonick**, combining **Acly's Krita AI Diffusion
1.53.0** with **FatGuy84's Krita AI Reloaded** and Krea 2 Edit V2 integration.
This is not an official release of either upstream project or Krea, and is not
endorsed by their authors.

## Build artifacts

The local build provides `krita_ai_diffusion-1.53.0-all-in-one.36.zip`, the corresponding
source ZIP and SHA-256 checksums under `builds/1.53.0-all-in-one.36/`. Published releases,
when available, are listed on the [project releases page](https://github.com/Teutonick/krita-ai-diffusion-all-in-one/releases).

Import the plugin ZIP through **Tools → Scripts → Import Python Plugin from File**,
then fully restart Krita. Configure workloads and optional components in Managed Server.

## What's included

- Upstream 1.53.0 and Reloaded's visual browsers, prompt tools, wildcard/batch workflows,
  history search/favorites/ratings, export integrations and other interface improvements.
- Krea 2 Turbo, Identity Edit V2, General Edit V2 and Remix integration.
- Managed installation of selected Krea Edit nodes and LoRA Manager dependencies;
  optional download/launch of the official Eagle installer.
- Protection against accidental value changes when scrolling over closed settings dropdowns.
- Session-based media storage and startup cleanup of abandoned plugin-owned sessions.

## Fixes in this build

- Add explicit Generate/Edit controls, a primary source selector and a Use active layer action.
- Add layer-context actions for editing and named prompt references, plus history actions to create a layer and edit/reference it.
- Fix Krea Turbo linked Edit preset resolution, including legacy display-name links; selecting a V2 Edit preset activates Edit mode and same-architecture extra LoRAs are retained.
- Preserve source selection by layer ID, reject missing/empty sources and report excess Krea input images instead of silently dropping them.
- Wrap full style-card names, label each task, add a task filter and keep long selected names from widening the dock.

- Build archives, checksums and source manifests now live under `builds/<version>/`, outside tracked source files.
- Packaging uses temporary staging with automatic cleanup and includes only the runtime WebSocket library and its license in the plugin ZIP.
- Remove unused ffmpeg preview code and unavailable private upstream publishing/upload commands. Test-fixture downloads remain available without private service credentials.

- Resolve the remaining 409 Dependabot occurrences through compatible dependency updates and shared downgrade protection.
- Preserve translation using an exact official Argos source revision where vulnerable Stanza is optional.
- Apply a tested Accelerate shard-path/regular-file guard after managed dependency installs and in Docker.
- Use verified Transformers consent-before-code-download behavior and compatible Diffusers/Hub/tokenizer versions.
- Add an offline advisory regression fixture; keep GPU-specific package indexes intact.
- See SECURITY-UPDATE.md for validation and the separately identified upstream Windows ROCm limitation.

- Critical dependency fixes: Pillow 13.0.0, certifi 2026.10.18, PyJWT 2.14.0 and uv 0.13.4 across affected Python locks.
- Shared minimum-version constraints apply to managed ComfyUI and custom-node dependency installation, preventing vulnerable downgrades.
- The managed server now requires a security update; the installer replaces outdated uv binaries and uses a version-specific installer cache. Existing model files are retained by the normal upgrade path.
- Documentation uses patched Astro/Starlight dependencies and no longer includes tar; npm audit reports zero vulnerabilities for the resolved tree.
- Bundled license snapshots are protected from Windows newline conversion so official SHA-256 verification survives Git checkout.

- Late Python-property bindings ignore deleted Qt receivers during application shutdown.
- Settings descriptions wrap and participate in Qt height-for-width layout; controls stay visible on narrower settings pages.
- Before each managed CivitAI model download, the plugin synchronizes its current API key and selected host with LoRA Manager. A failed synchronization stops the download with an explicit error.

- Preserve the required empty `preview_url` metadata field: LoRA Manager no longer rejects restored models after a restart.
- Always supplement the manager library with ComfyUI's actual LoRA file list, including models with missing metadata.
- Show a neutral LoRA icon when an online preview is unavailable; retain model selection and subfolder paths.
- Invalidate incomplete library caches written by the previous build. Preview resolution uses the configured CivitAI host and SHA-256 without requiring a metadata sidecar.

- Concurrent requests to start the managed server now share one startup task.
- If the default port is occupied, the managed server chooses an available port without
  stopping the other application. Explicitly requested busy ports produce a clear error.
- ComfyUI's SQLite database now receives an explicit session-specific `--database-url`;
  `--user-directory` alone did not isolate its default database.
- Older Krea UI workflows use server-declared defaults for newly added widgets instead
  of failing with an IndexError.

## Krea 2 Edit V2 model terms

**GPLv3 covers the plugin code, not the model weights.**
The setup dialog presents the V2 License, Krea 2 Community License and NOTICE and
requires explicit acknowledgement before downloading V2 weights. Complete copies
are included in the plugin and installed beside the models.

Free use of the V2 models is non-commercial. Commercial use of the models or their
outputs requires a separate written license from **Lars Bouaraba**; additional Krea
licensing may apply. Accepting the setup dialog does not grant commercial rights.
[Official model terms](https://huggingface.co/conradlocke/krea2-identity-edit/blob/main/LICENSE_V2.md)
· [Commercial licensing contact](mailto:l.bouaraba@gmail.com).

## Media retention

Automatic browser thumbnails stay in memory. Temporary transfers, animation frames,
managed-server media and LoRA Manager preview files use a session folder that is cleaned
on normal shutdown or recovered at the next startup after a crash. Metadata and favorites
may be cached without preview files. Explicit exports and `.kra` history remain.
External/cloud servers and arbitrary custom workflows require session-scoped approval.
Unidentified files in global TEMP and existing user model/output folders are not deleted.

## Source, licenses and credits

Both the plugin ZIP and the exact source ZIP contain the same source manifest. The source
archive includes modified sources, build scripts, the bundled WebSocket dependency and
license notices. No model weights or Eagle executable are embedded in these archives.

The combined plugin code is **GPLv3**. Separately downloaded components and models retain
their own licenses. See the included THIRD-PARTY-NOTICES.md and model license documents.

Thank you to **Acly and the Krita AI Diffusion contributors** for the original plugin,
and to **FatGuy84 and the Krita AI Reloaded contributors** for the workflow and UI
improvements. Credit also belongs to Lars Bouaraba / conradlocke, willmiao and the
contributors to the integrated components.

Report combined-build issues to [this fork](https://github.com/Teutonick/krita-ai-diffusion-all-in-one/issues).
Please reproduce an issue in the official build before reporting it upstream.

Modified on **2026-11-03**. Validation details and remaining acceptance limits are
included in BUILD-REPORT.md. GPU image-generation acceptance is not claimed by these notes.
