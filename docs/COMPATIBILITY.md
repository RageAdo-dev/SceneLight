# Compatibility

## Requirements

- **Windows:** the downloadable app includes its own Python and Preview components.
- **Ren’Py:** compatible Ren’Py 7 and 8 projects. Some older games can use the
  bundled Ren’Py 7.7.1 compatibility runtime.
- **Graphics:** OpenGL 3.3 or OpenGL ES 3.0 with supported floating-point rendering.
  A dedicated graphics card is not required.

CUDA can speed up preparation on supported NVIDIA hardware. It is optional and
does not replace the graphics requirements for live lighting.
The command-line tools can also be [installed from source](../CONTRIBUTING.md#development-setup);
the packaged desktop release targets Windows.

## What to expect

SceneLight works with separate character sprites. Full-screen painted scenes with
no separate sprites may have nothing to light. Automatic discovery cannot identify
every custom image setup; review the character checklist before installing.

Missing or unsupported assets are reported and skipped individually. Once the
artwork is added or repaired, run Scan/Update again. Newly added scenes and assets
need an update and a game restart before their prepared lighting is available.

Preview displays one sprite. Cast-light settings can be exported there, but their
effect on other characters must be checked in-game. Custom shaders and transforms
may also need [composition adjustments](MOD_AUTHOR_API.md#shaders-and-transforms).

## Tested coverage and limits

The 1.1.0 package was checked in Ren’Py 7.7.1 and 8.5.2 for player and developer
updates, save loading, and lighting groups. Current physical GPU checks used an
NVIDIA RTX 4090. An older build was checked on an AMD Radeon HD 6700M; the current
package still needs fresh AMD and Intel hardware checks.

These checks do not establish compatibility with every mod, driver or full
playthrough. [Report a problem](TROUBLESHOOTING.md) with your versions and a short
reproduction. Maintainers can use the [testing checklist](TESTING.md).
