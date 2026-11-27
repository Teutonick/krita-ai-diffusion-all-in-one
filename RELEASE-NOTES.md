# 1.53.0-all-in-one.76 — krita-ai-diffusion-all-in-one

MOSS image editing translates Prompt Box captions and scene context through
the local ComfyUI translation node. Graph tests verify that each box uses the
same configured LoRAs.

## 1.53.0-all-in-one.75

Prompt AI image edits reconcile the full shot while preserving compatible text.
Animation revisions reconcile action, camera, focus, and sound across the shot.

## 1.53.0-all-in-one.74

When WanGP MCP is unavailable, the video dialog offers MCP setup instructions
and can launch the selected local WanGP installation on Windows.

## 1.53.0-all-in-one.73

Managed Server reuses installed Argos translation packages and cached Stanza
resources. Missing translation resources can still be downloaded when needed.

## 1.53.0-all-in-one.72

MiniMax H3 video prompts describe actions and transitions in order, with
camera movement and sound tied to the scene. The revision tool preserves
requested action sequences and camera instructions.

## 1.53.0-all-in-one.71

WanGP video jobs target the workspace open in the WanGP gallery when submitted.

## 1.53.0-all-in-one.70

The first WanGP send and the integration settings explain how to enable MCP and
where to find the selected model's settings file relative to the WanGP folder.

## 1.53.0-all-in-one.69

**Generate prompt for video (ext)** sends video jobs to WanGP with the settings
saved through **Set Settings as Default** in Generate. The plugin rereads the
selected JSON on each click, independently of Deepy templates.

## 1.53.0-all-in-one.68

WanGP status tracking handles queued and running job snapshots without a
top-level status field so the plugin can wait for completion and clean up its
temporary upload.

## 1.53.0-all-in-one.67

- WanGP requests recover from a deleted workspace assignment and use the same
  workspace for the temporary upload, queue submission, status, and cleanup.
- Animation prompts use the visible first frame and the active image prompt
  to shape motion and story.

## 1.53.0-all-in-one.66

- Send the animation prompt and source frame to a running WanGP instance using
  its default video template. The plugin checks that ComfyUI has released GPU
  memory before submission and removes the temporary WanGP upload after the job.
- The LoRA browser picks up the active model architecture on each open and
  scrolls through cards in smaller steps.

## 1.53.0-all-in-one.65

H3 Make POVs uses camera instructions based on H3 Camera Prompt Adapter with
the existing Standard W4A8 checkpoint, text encoder, and VAE.

## 1.53.0-all-in-one.64

H3 Make POVs uses the shorter camera instructions from build .63.

## 1.53.0-all-in-one.63

H3 Make POVs applies enabled style LoRAs and LoRA tags in the prompt to every view.

## 1.53.0-all-in-one.62

Make POVs supports MiniMax H3 Image Standard W4A8 with six horizontal or five
vertical views. It uses the current canvas and the installed H3 models.
Camera angles are approximate.

## 1.53.0-all-in-one.61

The Plugin information page displays the NotBad by Teutonick badge.

## 1.53.0-all-in-one.60

The Resolution slider now displays the selected multiplier.
MOSS Edit warns before queuing large jobs and suggests a lower multiplier based on GPU memory.

## 1.53.0-all-in-one.59

The MiniMax H3 Image filter in the LoRA browser selects Image versions in CivitAI
and in the local library.

## 1.53.0-all-in-one.58

CivitAI searches use the MOSS Image server filter and show matching versions
of models published for multiple architectures.

## 1.53.0-all-in-one.57

Prompt AI updates the MOSS prompt box at the text cursor and preserves its coordinates.
Image descriptions use the area inside that box.

## 1.53.0-all-in-one.56

MOSS Edit prompt boxes use masked sampling on the source image, with feathered edges
inside each rectangle.

## 1.53.0-all-in-one.55

In MOSS Edit, Add prompt box applies each instruction inside its own rectangle.
The inactive region list scrolls when several regions are added.

## 1.53.0-all-in-one.54

Managed Server groups selectable models by family in a single Models tab.
MOSS Image includes generation checkpoints and Edit, with automatic dependencies.
Krea 2 Edit installs its ComfyUI nodes when an Edit model is selected.

## 1.53.0-all-in-one.53

MOSS Image supports reference editing with the optional MOSS Image Edit LoRA.
Use a Krita selection to restrict where the edit is applied. For generation,
Add prompt box records a rectangular selection and its own prompt.

## 1.53.0-all-in-one.52

Update svglib to 2.3.1 to address CVE-2026-132275. Update the managed server
after installing this build.

## 1.53.0-all-in-one.51

Restores Make POVs canvas previews during sampling and when selecting a result
in history. Applying a POV result still requires an explicit action.

## 1.53.0-all-in-one.50

Make POVs keeps generated images in session history until you explicitly apply
or export them. A new Make POVs section in the README shows the original
portrait and six local Krea 2 views and links to the component licenses.

## 1.53.0-all-in-one.49

Make POVs can switch between six horizontal views and five vertical views.

## 1.53.0-all-in-one.48

Make POVs preserves the source camera scale and uses the visible framing to
anchor camera turns for cropped subjects. Update the Make POVs server component.

## 1.53.0-all-in-one.47

Prompt AI can describe the main object or character from the canvas in English,
focusing on distinctive visual traits and omitting pose and scene details.

## 1.53.0-all-in-one.46

Make POVs uses an Anygles reference up to 768 pixels on the longest edge.

## 1.53.0-all-in-one.45

Make POVs applies explicitly tagged Krea 2 LoRAs to every viewpoint at their
prompt weights, before applying the Anygles camera adapter.

## 1.53.0-all-in-one.44

Make POVs uses neutral subject-preservation instructions alongside the active
prompt. Anygles still uses human-shaped geometry to guide the camera.
Update the installed server node under Managed Server.

## 1.53.0-all-in-one.43

Make POVs uses the active prompt as subject and scene context across the series.
With prompt context, it encodes a larger visual reference to retain subject details.
The installed Make POVs server node needs to be updated under Managed Server.

## 1.53.0-all-in-one.42

Make POVs tries full-frame subject reconstruction when the person detector misses a portrait.

## 1.53.0-all-in-one.41

Fixes Make POVs submitting its ComfyUI graph with an unserializable text encoder reference.

## 1.53.0-all-in-one.40

Adds optional Make POVs for Krea 2 Turbo on a managed NVIDIA CUDA server.
Enable it under Components, review the model terms, and install the
dependencies. Make POVs uses the visible canvas to queue six camera views
for scenes with one or two people. The results appear in Generation history.
Hidden surfaces and background details are reconstructed and may change.

## 1.53.0-all-in-one.39

Adds a dedicated Krea 2 Prompt AI profile with guidance for poses, points of
contact, spatial relationships, framing, and verbatim lettering.

Built-in Prompt AI profiles no longer prescribe fixed word, sentence, or tag
counts. Response Length sets the maximum number of output tokens.

Prompt AI's Modify with instruction applies exact text edits to the existing
prompt, preserving unrelated text, formatting, LoRA tags and wildcards.
Invalid or ambiguous edits leave the original prompt unchanged.

Local pytest scratch files and model weights are excluded from Git.

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
