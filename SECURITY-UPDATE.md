# Critical dependency security update

Prepared 2026-11-03 for `1.53.0-reloaded.7`. No commit, push, alert dismissal or user-server modification performed.

The GitHub snapshot contained 87 critical dependency occurrences representing 10 unique advisories. Every affected manifest occurrence has been checked against its advisory's first patched version. This is a source-manifest assessment, not proof that an existing installed server has already been updated.

| Advisory | Package | Resolution |
| --- | --- | --- |
| [GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2) | certifi | 2026.10.18 |
| [GHSA-5x8w-8jj5-q52h](https://github.com/advisories/GHSA-5x8w-8jj5-q52h) | pillow | 13.0.0 |
| [GHSA-v9pv-5gc8-w2m6](https://github.com/advisories/GHSA-v9pv-5gc8-w2m6) | Pillow | 13.0.0 |
| [GHSA-332p-7hrc-92wf](https://github.com/advisories/GHSA-332p-7hrc-92wf) | Pillow | 13.0.0 |
| [GHSA-w889-685w-c8fh](https://github.com/advisories/GHSA-w889-685w-c8fh) | Pillow | 13.0.0 |
| [GHSA-8g5g-8vmr-9782](https://github.com/advisories/GHSA-8g5g-8vmr-9782) | Pillow | 13.0.0 |
| [GHSA-hq85-5cpj-mr62](https://github.com/advisories/GHSA-hq85-5cpj-mr62) | uv | 0.13.4 |
| [GHSA-ffc3-869f-jxw9](https://github.com/advisories/GHSA-ffc3-869f-jxw9) | PyJWT | 2.14.0 |
| [GHSA-26w7-cxv4-gfx2](https://github.com/advisories/GHSA-26w7-cxv4-gfx2) | astro | 7.4.5 (with compatible Starlight 0.42.8) |
| [GHSA-23hp-3jrh-7fpw](https://github.com/advisories/GHSA-23hp-3jrh-7fpw) | tar | Removed from the resolved documentation dependency tree; override prevents reintroduction below 7.5.19. |

## Installation and retained protection

- All affected backend platform locks, legacy server requirements and Docker requirements use patched pins.
- `requirements/security.in` supplies minimum versions for managed ComfyUI and custom-node installs through both uv and pip. Backend input requirements also use these constraints.
- The managed installer replaces uv versions below 0.13.4, uses a versioned installer cache, and requests the normal managed-server upgrade through the new installation version. The upgrade path retains models.
- Docker bootstraps uv 0.13.4; development requirements inherit the same security floors.
- Documentation now requires Node >=22.12.0 and uses a compatible Astro/Starlight dependency tree. No --force or --legacy-peer-deps was used.
- Official model-license snapshots are protected from Git newline conversion, preserving their SHA-256 checks across Windows checkouts.

## Validation and limits

- All 87 original critical manifest occurrences checked: zero remaining; tar is absent rather than merely hidden.
- Full dependency resolution: 11 backend platform locks and Docker passed. Linux ROCm timed out streaming the pre-existing PyTorch wheel; it remains unvalidated.
- npm audit: zero vulnerabilities across all severities in the updated documentation tree. Production static build: 16 pages.
- Available Python CI under Pillow 13: 345 passed, 111 skipped, 9 deselected. The excluded cases require a separate live server or working standalone PyQt TLS. Ruff check/format and Pyright passed.
- Fresh installer integration attempted; standalone PyQt TLS failed downloading ComfyUI. A complete fresh Krita installation and GPU inference were not validated.
- Existing user-server packages were not modified. Install the updated plugin, restart Krita and complete the offered managed-server update to apply these dependency changes there.
- High/medium/low Python advisories outside this critical scope have not all been remediated. No claim of a completely vulnerability-free backend is made.
- GitHub alert status will change only after the changes are pushed and dependency analysis runs again.
