# Validation results

Current tester package: **1.1.0**. Documentation reviewed on 10 October 2026.

| Area | Recorded result |
| --- | --- |
| Automated suite | 1,026 tests passed locally; all six Windows/Linux CI jobs passed |
| Real game updates | Ren’Py 7.7.1 and 8.5.2, player and developer workflows |
| Save safety | Prior gameplay checkpoint loaded after adding a sprite/background |
| Existing data | Maps, settings and saved bytes preserved in the native rehearsals |
| Package | ZIP integrity passed; all 67 product source files matched the tested release code |
| Lighting groups | Shared position/settings, movement, hidden anchors and save/load on Ren’Py 7 and 8 |
| Project edits | Open Setup detected changes in both modes in about 10 seconds |
| Bright-scene lighting | Controlled Preview/native comparisons on 12 backgrounds |
| Large-file finalization | Earlier beta 27 benchmark; current timing remains unmeasured at that scale |
| Static/build checks | Ruff, formatting, dependency audit, Python build and medium/high security scan passed |

[Compatibility, current results and known issues](docs/BETA_VALIDATION.md) ·
[Performance methodology](docs/performance.md) · [Validation checklist](VALIDATION.md)

The tester reported that updating newly added scenes cleared the shimmer.
Version 1.1.0 detects those edits while Setup stays open; confirmation in the
reporting mod is still pending. Current checks do not cover a full playthrough
or fresh AMD/Intel hardware. [Useful reporting steps](docs/TROUBLESHOOTING.md).

[Earlier investigation records](docs/history/validation-2026-09-18.md).
