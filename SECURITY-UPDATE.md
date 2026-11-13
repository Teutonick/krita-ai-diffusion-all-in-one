# Dependency security update — 1.53.0-reloaded.8

Prepared 2026-11-03. No commit, push, alert dismissal or user-server package modification performed.

## Scope and result

The new GitHub snapshot contained **409 open occurrences, representing 65 unique advisories**: 124 high, 225 medium and 60 low. All affected manifest versions now fall outside those recorded vulnerable ranges. The previous critical fixes are retained and regression-tested alongside them. GitHub status itself will change only after these changes are pushed and dependency analysis runs again.

This is a check against a dated advisory snapshot, not a guarantee that every dependency or platform is free of vulnerabilities. In particular, two advisories have no official patched-version field, so their code paths were reviewed and tested rather than relying only on version comparisons.

## Updated dependencies

- aiohttp 3.14.5, filelock 4.2.1, GitPython 3.2.1, Mako 1.4.2, multidict 6.9.1, pip 26.2.0, Protobuf 5.29.6 or newer compatible existing pins, PyJWT 2.15.0, SentencePiece 0.2.1, setuptools 84.1.0, Stanza 1.12.2 and urllib3 2.8.0.
- Diffusers 0.38.0 and Transformers 5.22.1; compatible tokenizers and Hugging Face Hub versions are locked. Hub is kept below 2 for Diffusers compatibility.
- Docker now uses PyTorch 2.13.0 with torchvision 0.28.0 and a resolver-selected compatible CUDA dependency tree. Other backend GPU indexes and wheels retain their original hardware targets.
- Critical fixes from .7 remain: Pillow 13.0.0, certifi 2026.10.18 and uv 0.13.4 (plus the newer PyJWT update above).
- Shared constraints apply both when installing the backend and when adding custom-node requirements, preventing vulnerable dependency downgrades.

## Argos translation compatibility

The released Argos Translate 1.11.0 pins vulnerable Stanza 1.10.1. Instead of forcing an incompatible dependency override, this build uses the official upstream source at commit `17ed1a9b055c5ba1b51d76b683bbb0c64e2a4a88` (version 1.11.1), where Stanza is optional and MiniSBD remains the default. The source URL is fixed in all affected manifests and shared constraints. Translation functionality is retained; the updated package was built and imported in the isolated compatibility check.

Source: https://github.com/argosopentech/argos-translate/tree/17ed1a9b055c5ba1b51d76b683bbb0c64e2a4a88

## Advisories requiring code verification

### Accelerate: GHSA-4j2p-28q2-5m79

Accelerate 1.15.0 is outside the advisory's recorded affected range, but source inspection showed that its loader still joins untrusted shard paths without containment validation. A version bump alone is insufficient.

The installer now applies a narrowly scoped source hardening after dependency installation. It rejects absolute paths, parent-directory escapes and non-regular shard files before loading them. Ordinary nested shard paths and regular-file Hub-cache symlinks remain usable. The transformation is atomic, idempotent and refuses unknown upstream source layouts rather than claiming protection. Docker applies the same helper. A real Accelerate load against a malicious index was rejected before shard loading.

This protection addresses model-supplied index paths and non-regular files; it is not a sandbox against a local attacker concurrently modifying the model directory.

### Transformers: GHSA-x9r9-c232-4q39

The advisory has no patched-version field. The inspected 5.15.1 implementation still downloaded a generation module before trust consent. Version 5.22.1 checks file existence without downloading it, obtains trust consent, and only then downloads the module. The real API was exercised with trust disabled and a download spy: no code download occurred.

## Validation

- All 409 remaining manifest occurrences are checked against the original advisory ranges. The earlier critical advisory snapshot is also covered by the offline regression fixture.
- Full dependency resolution passed for all 12 backend platform locks, Docker and the legacy requirements.
- Real isolated CPU imports passed with PyTorch 2.13.0+cu130, Transformers 5.22.1, Accelerate 1.15.0, Diffusers 0.38.0 and the pinned Argos source.
- Accelerate's path protection and Transformers' consent-before-download ordering were exercised using the actual installed libraries.
- Isolated managed ComfyUI started successfully with the final dependency overlay; both bundled Krea workflows imported (26 and 23 nodes). The test server stopped and its temporary session was removed. Existing user-server packages and processes were not modified.
- Python CI: 354 passed, 112 skipped, 9 deselected. Ruff check/format and Pyright passed. POSIX FIFO execution is skipped on Windows; a non-regular-file rejection case runs there.
- Documentation dependencies are unchanged from the verified .7 update: npm audit reported zero vulnerabilities and the static site built successfully.

## Applying the update and limits

Install the .8 plugin ZIP, restart Krita and complete the offered Managed Server update. Replacing plugin files alone does not update packages already installed in the server. The normal upgrade path retains model files.

Fresh installer integration was attempted; standalone PyQt failed TLS initialization downloading ComfyUI. Complete fresh installation in Krita, GPU inference and an actual Docker image build are not claimed as validated.

**Windows ROCm limitation:** AMD's official 7.2.1 Windows wheel repository still provides PyTorch 2.9.1, while GHSA-rrmf-rvhw-rf47 lists PyTorch <=2.12.1 as affected. These direct-URL wheels were not part of the GitHub alert occurrences being remediated. They have not been silently replaced with incompatible CUDA/CPU wheels or disabled. Windows ROCm therefore retains this separate upstream risk; the NVIDIA/CPU/Linux locks and updated Docker use PyTorch 2.13.0. An appropriate patched AMD Windows build is still needed.

## Dictation and Pose Studio media lifetime

- Audio is captured locally. A transcription subprocess uses a private staging
  directory in the locked media session. Normal completion/cancellation removes
  it; orphaned sessions are swept at the next plugin startup. Only model weights
  and the runtime are installed persistently. Recognized text follows normal
  prompt and document persistence.
- Pose Studio serves content on loopback with session URLs, origin checks for
  writes, and no-store responses. The embedded web view uses an off-the-record
  profile. When Qt WebEngine is unavailable, opening Pose Studio launches the
  default browser. Its history, downloads and
  backups are outside the plugin's control.
- Applying a pose explicitly attaches its editable state and PNG guide to the
  document. Saving a library entry explicitly stores its pose and any image or
  video preview in the local SQLite library. Deletion enables SQLite secure
  delete for the database operation; it does not remove historical backups.
