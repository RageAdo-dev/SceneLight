# Rendering status

Preview and Ren'Py share the scene analyzer and lighting shader. Static scenes
reuse their analysis; supported movies use lighting prepared for every frame.
Backgrounds changed by code or effects can use live analysis.

Sprite maps are prepared separately. Form-map version 9 smooths the broad
silhouette while retaining finer painted relief, and reads painted shading at
form scale so painted band boundaries stay flat. Moving a character reuses those
maps and changes its lighting at the new screen position.

See [Architecture](ARCHITECTURE.md) for the implementation and
[Compatibility and validation](BETA_VALIDATION.md) for measured results and limits.

The [9 September implementation record](history/live-analysis-2026-09-09.md)
retains the earlier live-only measurements. It predates prepared movie playback,
the final memory fixes and the current surface maps.
