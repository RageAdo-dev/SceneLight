# Developer effect packs

> Post-launch development reference. Rain, glitch, and custom effect packs are
> deferred to a later update and are not part of the launch feature guide.

Add custom GPU effects with JSON packs and the `scenelight_fx` API. Packs are
controlled from your game's scripts; the player effects panel and hotkey are
disabled. The source package includes example packs.

## Add a pack

Place a JSON file in `game/scenelight_effects/`, then run **Update SceneLight**.
Invalid packs are skipped and reported. Built-in rain and glitch need no pack.
These experimental controls are outside the current lighting guide.

This example adds a configurable color effect:

```json
{
  "format": "scenelight-effect-pack",
  "version": 1,
  "id": "my_pack",
  "name": "My Pack",
  "author": "Your name",
  "license": "MIT",
  "effects": [
    {
      "id": "cold_tint",
      "name": "Cold Tint",
      "parameters": {
        "intensity": {"type": "float", "default": 0.0, "min": 0.0, "max": 1.0},
        "tint": {"type": "vec3", "default": [0.5, 0.8, 1.0], "min": 0.0, "max": 1.5}
      },
      "fragment": "gl_FragColor.rgb *= mix(vec3(1.0), u__tint, u__intensity);"
    }
  ]
}
```

Enable it by `<pack id>.<effect id>`:

```renpy
$ scenelight_fx.character("hero", "my_pack.cold_tint", intensity=0.6)
$ scenelight_fx.clear_character("hero", "my_pack.cold_tint")
```

`scenelight_fx.scene(...)` applies an effect to all selected characters. Effects
have separate state from lighting and can remain active when lighting is off.
Test custom packs with your project's sprites, transforms and target renderer.

## Format

Identifiers start with a lowercase letter or underscore and contain at most 48
lowercase letters, numbers or underscores. Parameters support
`float`, `vec2`, `vec3` and `vec4`. Every effect needs a float `intensity` with a
zero default. Shader parameters use the `u__` prefix; Ren'Py assigns their namespace.

Fragments can use `v_tex_coord`, `u_time` and `gl_FragColor`. To sample the lit
character, add `"source_texture": true` and use `texture2D(tex0, uv)`. SceneLight's
private lighting textures are not exposed.

An effect may select a built-in `preset` and override its `defaults`. A preset
cannot also replace its fragment, parameters or source-texture contract.
The source package includes examples in [`examples/effect-packs`](../examples/effect-packs);
the same files are kept in the
[source tree](https://github.com/RageAdo-dev/SceneLight/tree/main/examples/effect-packs).

## Limits and composition

| Limit | Maximum |
| --- | ---: |
| Pack size | 256 KiB |
| Effects per pack | 16 |
| Parameters per effect | 16 |
| Custom fragment length | 8,192 characters |
| Character texture reads per effect | 8 |

Custom fragments cannot declare uniforms, use preprocessor directives or loops,
alter geometry, or access SceneLight's transport data. Validation checks names,
ranges and parameter references before generating runtime files.

Effects run after character lighting, with an alpha guard to preserve valid
premultiplied color. An authored outer `show ... at` shader remains a later,
separate pass. Raw `.rpy` shaders remain ordinary game code and are not imported
as JSON effect packs.
