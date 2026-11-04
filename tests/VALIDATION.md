# Krea2 validation — 2026-11-04

## Result and scope

- Windows fast suite: **380 passed, 121 skipped** (`tests --ci`).
- Ruff check, Ruff format check, and Pyright: passed.
- Krea2 Identity Edit V2 and General Edit V2 GPU tests: **2 passed in 46.86 seconds**.
- ComfyUI API preflight and a real image-only queue/execute/download smoke: passed.
- External HTTPS download: **not accepted**. The development PyQt5 runtime cannot
  locate OpenSSL by default. Attempts to supply the installed Krita SSL DLLs made
  `supportsSsl()` succeed but caused a native access violation during the download.
  No DLLs or PATH workarounds are installed or shipped with the plugin.

This validates local Krea2 editing, not every plugin feature or a complete release
acceptance. Cloud, full installer, animation, UI interaction inside Krita, and the
remaining inference tests were not accepted in this run. Skipped tests are not passes.

## Defects fixed

PyQt5's generated plugin path was corrupted by non-ASCII characters in the Windows
checkout path. Tests now explicitly register the virtualenv's Qt plugins, restoring
JPEG/WebP readers and writers. Image, mask, history, and API tests pass again.

The fast suite no longer starts a model-dependent ComfyUI fixture. The invalid-URL
test runs independently. Download/resume tests use a local HTTP server, assert the
actual Range request, and compare every received byte. A separate HTTPS integration
test preserves real TLS coverage rather than treating local HTTP as TLS validation.

The generated Krea2 graphs were missing `Krea2EditModelPatch` in the full-image
`refine` and masked `refine_region` paths. Both now attach the image/latent patch
before sampling. Eight fast graph regressions cover both presets, both paths, and
CFG 1/2, including grounded negative conditioning when CFG is above 1.

## GPU environment and evidence

The test process used ComfyUIClear's Python and ComfyUI 0.29.2, RTX 4070 Ti SUPER
(16 GB), and a workspace-local copy of the already installed Krea2 Edit 2.0.0 nodes.
The V2 weights and Qwen3-VL encoder were read from the managed server's `models`
directory; Qwen Image VAE was read from the shared model library. Neither existing
ComfyUI installation was updated or reconfigured. Input/output/temp/user folders and
the copied custom nodes were isolated under `.pytest_cache/comfy-production`; the
test database was in memory and the server listened only on loopback port 8197.

Both tests use Turbo FP8, a single edit LoRA at strength 1, 8 Euler/simple steps,
CFG 1, seed 1234, a 512×512 source portrait, and a background-change instruction.
The graph is built by `workflow.create`. Only the image transport nodes are replaced
with native upload/LoadImage/SaveImage so the isolated server does not need tooling
nodes. This does **not** test the plugin's ETN cache transport or its Krita UI.

The first General run timed out across a long interruption while its server job
eventually succeeded. A subsequent uninterrupted run passed both tests. The saved
portraits were visually inspected: the face and framing remain similar while the
background changes to a garden. This single example is not a likeness benchmark.

## Repeating checks

From the repository root on Windows:

```powershell
pwsh -NoProfile -File scripts/test.ps1
```

The runner uses `.venv`, redirects TEMP/TMP to `.pytest_cache/tmp`, runs formatting,
linting, type checking and fast tests, and restores environment variables afterward.
Run outside restrictive sandboxes if Windows file permissions prevent the checks.

For an already configured isolated V2 server:

```powershell
.venv/Scripts/python.exe scripts/check_krea2_server.py --url http://127.0.0.1:8197 --smoke
$env:AI_DIFFUSION_TEST_URL = 'http://127.0.0.1:8197'
$env:TEMP = Join-Path $PWD '.pytest_cache/tmp'
$env:TMP = $env:TEMP
.venv/Scripts/python.exe -m pytest tests/test_krea2_integration.py -v
```

The smoke submits an image-only job. The GPU tests upload a fixture and submit two
diffusion jobs; use a dedicated test process and output directory. Preflight alone
loads no weights. A GPU test timeout does not cancel the server job: inspect its
queue before rerunning. Full-image graph regressions also run in the fast suite.

The separate TLS check requires a compatible, working Qt/OpenSSL test runtime:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_server.py::test_https_download -v
```
