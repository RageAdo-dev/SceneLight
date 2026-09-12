# Animation timing validation

Current playback combines [prepared movie lighting](prepared-playback.md) with
[live analysis and light continuity](live-continuity.md). See
[Compatibility and validation](BETA_VALIDATION.md) for the latest recorded checks.

The [5 September timing audit](history/temporal-validation-2026-09-05.md)
reproduced frozen lighting in the older cached-timeline implementation and
verified its resolver correction. Its 8 Hz sampling limit and four-second
source-discovery window describe that historical path, not prepared per-frame
movie playback or the current live analyzer.

The original observations, mismatches and reproduction procedure remain in the
historical record.
