# SceneLight effect packs

> Internal next-update draft. This feature is dormant and is not included or
> advertised in the SceneLight 1.0.0 package.

SceneLight effect packs are shareable JSON files that add GPU character effects
without adding Python or replacing SceneLight's lighting shader. Put a pack in:

```text
game/scenelight_effects/<pack-name>.json
```

Run **Update SceneLight** after adding or changing a pack. Invalid packs are
skipped and listed in the install report; they do not stop the rest of the game
from installing.

The included examples are:

- `examples/effect-packs/horror_signals.json`
- `examples/effect-packs/environmental_atmosphere.json`
- `examples/effect-packs/impossible_geometry.json`
- `examples/effect-packs/divine_power.json`
- `examples/effect-packs/nightmare_transfigurations.json`

Copy any file into the project's `game/scenelight_effects` folder and update
SceneLight. Then use the same rollback-safe effects API as the built-in rain and
glitch effects:

```renpy
label haunted_hall:
    scene bg corridor_night
    show sayori worried

    $ scenelight_fx.character(
        "sayori",
        "horror_signals.spectral_presence",
        intensity=0.82,
        tint=(0.42, 0.74, 1.0),
        pulse=1.6,
    )

    s "Did you hear that?"

    $ scenelight_fx.clear_character("sayori", "horror_signals.spectral_presence")
```

Use `scenelight_fx.scene(...)` to apply an effect to every SceneLight-selected
character in the scene. Character settings override scene settings. An effect
continues to work when lighting is disabled, while lighting strength remains
zero. It also works when the current procedural, video, or unusual background
has no SceneLight lighting record. Ordinary `show`, `hide`, ATL, dissolve,
movement, rollback, and save/load behavior stay under Ren'Py's control.

## Pack format

Each pack contains metadata and one or more effects:

```json
{
  "format": "scenelight-effect-pack",
  "version": 1,
  "id": "my_horror_pack",
  "name": "My Horror Pack",
  "author": "Your name",
  "license": "MIT",
  "effects": [
    {
      "id": "cold_ghost",
      "name": "Cold Ghost",
      "description": "A cold spectral fade.",
      "parameters": {
        "intensity": {
          "type": "float",
          "default": 0.0,
          "min": 0.0,
          "max": 1.0
        },
        "tint": {
          "type": "vec3",
          "default": [0.5, 0.8, 1.0],
          "min": 0.0,
          "max": 1.5
        }
      },
      "fragment": "gl_FragColor.rgb = mix(gl_FragColor.rgb, gl_FragColor.rgb * u__tint, u__intensity);"
    }
  ]
}
```

Pack and effect identifiers use lowercase letters, numbers, and underscores.
The public effect name is `<pack id>.<effect id>`. Every effect must have a
float `intensity` parameter whose default is `0.0`, making installed effects
visually inert until a developer enables them.

The included `divine_power` and `nightmare_transfigurations` packs select
trusted built-in recipes with a `preset` field. Their JSON may override the
documented defaults without duplicating shader code. A preset entry cannot also
replace its fragment, parameter contract, or helper functions. This keeps the
portable pack declarative while SceneLight owns and tests the heavier animated
implementation.

The built-in live VFX are entirely GPU-driven. Lightning God combines branching
discharges, turbulent aura, glow, and sparks; Inferno Incarnate combines
source-bound flame layers and embers; The Legend combines a surging green field,
an expanding shockwave, pillars, and rising particles. Eyes Everywhere samples
the character's actual eye pixels, then animates independently moving and
blinking copies across the character. It uses `eye_center` and `eye_size` so an
author can calibrate a different art style without replacing the effect.

Supported parameter types are `float`, `vec2`, `vec3`, and `vec4`. Shader code
refers to a parameter named `tint` as `u__tint`. Ren'Py expands this shader-local
name into the pack's private namespace, preventing collisions with SceneLight,
Ren'Py, MVN, or another effect pack. The standard `v_tex_coord`, `u_time`, and
`gl_FragColor` values are available. A fragment must modify `gl_FragColor`.

Effects that deform, repeat, voxelize, or otherwise move character pixels can
opt into the already-lit character texture:

```json
"source_texture": true
```

The fragment can then read it with `texture2D(tex0, uv)`. SceneLight runs these
effects in a separate post-lighting texture pass, so `tex0` includes the normal
SceneLight result rather than bypassing it. A pack may perform at most eight
source reads per effect. Reads from SceneLight's lighting atlases or another
effect's intermediate buffers are never exposed.

## Composition and safety

SceneLight registers pack effects as Ren'Py model shader parts at fragment
priority 600. The established lighting shader runs at priority 350. The result
is a deliberate pipeline:

```text
character art -> SceneLight lighting -> selected effect-pack parts -> screen
```

SceneLight adds a fixed alpha-safety part at priority 900 after the selected
packs. It preserves premultiplied-alpha bounds, so color additions and authored
alpha fades cannot expose fully transparent pixels as a rectangular canvas or
edge halo. Opaque character pixels are unchanged by this guard.

Pack fragments cannot declare uniforms, replace textures, read anything except
an explicitly requested `tex0` character input, access SceneLight's internal
transport textures/uniforms, alter geometry, use GLSL preprocessor directives,
or create loops. Pack size, effect count, source-read count, parameter count,
source length, identifiers, numeric ranges, and parameter references are
validated before runtime files are generated. This is intentionally a visual
effect format, not an arbitrary-code plugin format.

These constraints make packs portable across Ren'Py's model renderer targets,
including the restrictive GLSL ES profile used by web and mobile. They also
keep third-party shader parts independent from existing Ren'Py/MVN transforms:
an authored outer `show ... at SomeTransform` remains a separate later pass.

Raw `.rpy` shaders are still normal Ren'Py code and can be used by developers
directly, but they are not treated as trusted SceneLight effect packs and are
not imported automatically.
