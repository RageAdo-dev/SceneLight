# How SceneLight works

SceneLight reads the background’s light and color, then uses each sprite’s
surface maps to shade the character at its current position.

![SceneLight before and after](media/lighting-comparison.png)

## Surface maps

![Sprite, height map, normal map and ambient occlusion](media/surface-maps.png)

- **Height map:** estimates the surface’s shape from the outline and painted shading.
- **Normal map:** tells the renderer which way each part of the surface faces.
- **Ambient occlusion:** adds shading in small recesses.

The broad outline is smoothed separately from fine painted detail to prevent
artificial creases. The original artwork and transparency are preserved.
These maps estimate depth from a flat image; they are not a recovered 3D model.

## Moving characters and backgrounds

Lighting responds to the character’s position, including movement through ATL
and transitions. Preview uses the same lighting shader as the game.

![A character moving between warm and blue lights](media/moving-light.webp)

Character maps are prepared once and reused across scenes. Supported videos
also get lighting data for every frame during setup. Backgrounds changed by
code or visual effects can use live analysis.

[Preview and installation](INSTALL.md) · [Author API](MOD_AUTHOR_API.md) · [Image credits](media/CREDITS.md)
