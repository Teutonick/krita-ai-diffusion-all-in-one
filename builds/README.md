# Local build artifacts

Generated release files live in `builds/<version>/`:

- Installable plugin ZIP.
- Matching source ZIP.
- `SOURCE-MANIFEST.json` containing exact source hashes.
- `SHA256SUMS-<version>.txt` covering both archives.

Run `python scripts/package.py build` from the repository root to create a release.
Only this README is tracked in Git. Publish the ZIPs and checksums as GitHub release
assets; keep matching source and license documents available with each build.
Previous local archives are retained in their version folders without modification.
