# Validation matrix

Every release must pass all three integration categories:

| Target | Required checks |
|---|---|
| Generic Ren'Py | Original synthetic project installs, compiles, opens, and the moving sprite's sampled lighting changes with position. |
| Local DDLC project | Scanner finds the four stock Character image tags without name presets; installed runtime compiles/lints and transition/movement checks pass. |
| Independent DDLC mod | Clean third-party checkout remains unmodified outside the local validation copy; SceneLight installs from local assets, compiles, and renders a controlled scene. |
| Preview & Calibrator | Production shader compiles in OpenGL; default Relit matches the runtime; Original is unchanged; calibration round-trips into a versioned manifest. |

Every release archive must also be installed into a temporary Python
environment from the archive itself. Run scan/install/verify/remove against an
original synthetic project, hash the selected project before and afterward,
and confirm the hashes are identical. The archive inventory must contain no
private game assets, generated maps, caches, user-specific paths, or local
development artifacts. Dependency-install validation must redirect
`SCENELIGHT_COMPONENT_ROOT` into the temporary test root, prove the selected
project hash is unchanged, and remove that temporary component environment at
the end.

The exact base, Preview, packaging-tool, and optional CUDA dependency sets must
pass the configured vulnerability audit. Generated Windows launchers must also
be tested with spaces, percent signs, and environment-variable-like text in
their paths so a path cannot become a batch command or variable expansion.

Before a public release, complete the disposable Windows procedure in
`docs/FRESH_MACHINE_VALIDATION.md`. A virtualized-GPU result is a compatibility
check only; retain a separate physical-GPU shader compile and visual parity
result.

Optional effects additionally require:

- a real GL2 capture with every effect disabled that is byte-identical to the
  protected pre-effects capture;
- live visual captures for rain/wetness and glitch/corruption;
- scene-wide and character-specific state checks with multiple characters;
- actual Ren'Py save/load and rollback restoration, skip stability, saved-game
  procedural timing, and transition stability; and
- a player-panel capture confirming that only supported effects are exposed.

Validation projects, downloaded mods, source game assets, generated maps, and
captures are deliberately not part of the public repository.
