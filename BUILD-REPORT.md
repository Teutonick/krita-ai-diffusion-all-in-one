# Build validation

Current plugin: `1.53.0-reloaded.9`. Managed-server dependency version remains `.8` because this cleanup does not change server requirements.

This unofficial combined fork includes Acly 1.53.0, FatGuy84's Reloaded improvements and Krea 2 Edit integration. Attribution, source revisions and license terms are documented in THIRD-PARTY-NOTICES.md and the source manifest embedded in each release archive.

## Repository and packaging

- All local release archives and checksum files are stored under `builds/<version>/` and excluded from Git. Existing archives were moved without changing their SHA-256 hashes.
- New builds place both ZIPs, the shared source manifest and checksums in that directory. Temporary packaging space is cleaned automatically.
- The installable ZIP includes WebSocket runtime sources and the BSD license; upstream examples, experiments and dependency test suites stay out of the plugin installation. Complete dependency sources remain in the corresponding source archive.
- Removed unused ffmpeg preview extraction, unavailable private upstream publishing/upload commands and unused development dependencies. Online preview behavior and test-fixture downloads are retained.
- Generated source manifests are no longer tracked in the repository root. Both release ZIPs still contain the same manifest, and an extracted source archive can rebuild without Git.

## Validation

- Ruff check/format and Pyright passed.
- Available CI: 355 passed, 112 skipped, 9 deselected. Windows TEMP/TMP are confined to the working copy. The excluded pre-existing cases require a live test server or working standalone PyQt TLS.
- Source packaging tests cover exact file hashes, exclusion of private/generated files, dedicated artifact output and rebuilding an extracted snapshot without Git.
- ZIP integrity, matching manifests, source hashes, license SHA-256 values, artifact checksums and imports from the trimmed plugin archive checked after packaging.

## Retained security validation

The .8 dependency update covered the 409 remaining Dependabot occurrences and retained earlier critical fixes. All 12 backend platform locks, Docker and legacy requirements resolved. Real CPU imports, isolated ComfyUI startup and both bundled Krea workflow imports passed. Accelerate's shard guard and Transformers' consent-before-download behavior were exercised against the actual libraries.

See SECURITY-UPDATE.md for the advisory scope and Windows ROCm upstream limitation. Complete fresh installation in Krita, GPU inference and an actual Docker image build remain unverified. The previous fresh-installer attempt was blocked by standalone PyQt TLS initialization. No user-server packages or processes were changed during this cleanup.
