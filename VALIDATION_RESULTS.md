# Validation results

Current tester package: **beta 28**. Documentation reviewed on 5 October 2026.

| Area | Recorded result |
| --- | --- |
| Automated suite | 1,004 tests passed locally |
| Real game updates | Ren’Py 7.7.1 and 8.5.2, player and developer workflows |
| Save safety | Prior gameplay checkpoint loaded after adding a sprite/background |
| Existing data | Maps, settings and saved bytes preserved in the native rehearsals |
| Package | ZIP integrity passed; all 66 product source files matched the tested code |
| Bright-scene lighting | Controlled Preview/native comparisons on 12 backgrounds |
| Large-file finalization | Earlier beta 27 benchmark; beta 28 timing remains unmeasured at that scale |
| Static/build checks | Ruff, formatting, dependency audit, Python build and medium/high security scan passed |

[Compatibility, current results and known issues](docs/BETA_VALIDATION.md) ·
[Performance methodology](docs/performance.md) · [Validation checklist](VALIDATION.md)

The recent long-session shimmer report remains under investigation. Current native
and GPU checks do not establish full-mod playthrough coverage or fresh AMD/Intel
compatibility. [Useful reporting steps](docs/TROUBLESHOOTING.md).

[Earlier investigation records](docs/history/validation-2026-09-18.md).
