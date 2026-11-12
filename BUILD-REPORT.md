# Build validation

Current plugin: 1.53.0-all-in-one.29. Includes the local Pose Library and the Krea 2 Pose Studio reference placement fix. The placement was verified with Krea 2 Turbo and Identity Edit V2 on seed 12342. Historical validation is listed below.

This unofficial combined fork includes Acly 1.53.0, FatGuy84's Reloaded improvements and Krea 2 Edit integration. Attribution, source revisions and license terms are documented in THIRD-PARTY-NOTICES.md and the source manifest embedded in each release archive.

## Repository and packaging

- All local release archives and checksum files are stored under `builds/<version>/` and excluded from Git. Existing archives were moved without changing their SHA-256 hashes.
- New builds place both ZIPs, the shared source manifest and checksums in that directory. Temporary packaging space is cleaned automatically.
- The installable ZIP includes WebSocket runtime sources and the BSD license; upstream examples, experiments and dependency test suites stay out of the plugin installation. Complete dependency sources remain in the corresponding source archive.
- Removed unused ffmpeg preview extraction, unavailable private upstream publishing/upload commands and unused development dependencies. Online preview behavior and test-fixture downloads are retained.
- Generated source manifests are no longer tracked in the repository root. Both release ZIPs still contain the same manifest, and an extracted source archive can rebuild without Git.

## Validation

- Ruff check/format and Pyright passed.
- Available CI: 366 passed, 112 skipped, 9 deselected. Windows TEMP/TMP are confined to the working copy. The excluded pre-existing cases require a live test server or working standalone PyQt TLS.
- Source packaging tests cover exact file hashes, exclusion of private/generated files, dedicated artifact output and rebuilding an extracted snapshot without Git.
- ZIP integrity, matching manifests, source hashes, license SHA-256 values, artifact checksums and imports from the trimmed plugin archive checked after packaging.

## LoRA browser validation

- Add to Prompt targets the active Generate/Edit region; strict base-model filters exclude unknown metadata while Any retains all files.
- Scan server refreshes existing entries and fetches missing triggers/base-model metadata by exact CivitAI hash. Missing matches retain local entries.
- Browser list/enrichment caches are RAM-only. Tests verify triggers with an existing preview, no disk writes, session cache reset and both prompt modes. Preview images remain RAM-only.

## Edit workflow validation

- Krea 2 Edit resolves the linked Identity V2 preset and preserves additional generation-style LoRAs when the architectures match. Selected-layer pixels, rather than the visible composition, reach the workflow input in the new pipeline test.
- Tests cover source deletion, rename-stable named references, history-to-layer actions and the two-image Krea input limit.
- Offscreen Qt checks cover the task/source controls, wrapped style cards at 760 pixels and insertion into a simulated native Layers context menu. Actual Krita menu interaction and GPU output remain unverified.
- Workflow integration: 8 passed before the first inference case stopped because the test server lacks the Default Style checkpoint (`not-found`).

## Retained security validation

The .8 dependency update covered the 409 remaining Dependabot occurrences and retained earlier critical fixes. All 12 backend platform locks, Docker and legacy requirements resolved. Real CPU imports, isolated ComfyUI startup and both bundled Krea workflow imports passed. Accelerate's shard guard and Transformers' consent-before-download behavior were exercised against the actual libraries.

See SECURITY-UPDATE.md for the advisory scope and Windows ROCm upstream limitation. Complete fresh installation in Krita, GPU inference and an actual Docker image build remain unverified. The previous fresh-installer attempt was blocked by standalone PyQt TLS initialization. No user-server packages or processes were changed during this update.
