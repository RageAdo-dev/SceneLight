"""Compile the production Ren'Py shader body inside a desktop OpenGL wrapper."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..runtime import shader_stages
from ..runtime.shader_stages import build, vertex_preamble
from .core import runtime_source_path


def _extract(name: str) -> str:
    text = runtime_source_path().read_text(encoding="utf-8")
    runtime_name = f"_scenelight_shader_{name}"
    match = re.search(
        rf"\b{runtime_name}\s*=\s*(?:_scenelight_fragment_source\s*\(\s*)?\"\"\"(.*?)\"\"\"",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError(f"Could not extract {name} from the production shader")
    return match.group(1)


def production_shader_sha256() -> str:
    digest = hashlib.sha256(runtime_source_path().read_bytes())
    digest.update(Path(shader_stages.__file__).read_bytes())
    return digest.hexdigest()


def vertex_source(*, center_samples: bool = False) -> str:
    source = """#version 330 core
in vec2 in_unit;
in vec2 in_uv;
uniform vec2 u_canvas_size;
uniform vec2 u_sprite_position;
uniform vec2 u_sprite_size;
uniform vec2 u_sc_form_center;
uniform float u_sc_render_local;
out vec2 v_tex_coord;
out vec2 v_sc_screen;
out vec2 v_sc_center;

void main() {
    vec2 pixel = u_sprite_position + in_unit * u_sprite_size;
    vec2 clip = vec2(
        pixel.x / u_canvas_size.x * 2.0 - 1.0,
        1.0 - pixel.y / u_canvas_size.y * 2.0
    );
    gl_Position = vec4(clip, 0.0, 1.0);
    if (u_sc_render_local > 0.5) gl_Position = vec4(in_unit * 2.0 - 1.0, 0.0, 1.0);
    v_tex_coord = in_uv;
    v_sc_screen = pixel / u_canvas_size;
    v_sc_center = (u_sprite_position + u_sc_form_center * u_sprite_size) / u_canvas_size;
}
"""
    if center_samples:
        declarations, helpers, body, _ = build(
            _extract("fragment_functions"), _extract("fragment_350")
        )
        helpers, body = vertex_preamble(_extract("variables"), helpers, body)
        source = source.replace(
            "void main() {",
            declarations.replace("varying ", "out ") + "\n" + helpers + "\nvoid main() {",
        )
        end = source.rfind("}")
        source = source[:end] + body + "\n" + source[end:]
        source = source.replace("texture2D", "texture")
    return source


def fragment_source(*, center_samples: bool = False) -> str:
    variables = _extract("variables")
    body = _extract("fragment_350")
    if center_samples:
        declarations, _, _, body = build(_extract("fragment_functions"), body)
        variables += "\n" + declarations
    variables = re.sub(r"\bvarying\s+", "in ", variables)
    # These are supplied by Ren'Py's base texture shader in-game. The desktop
    # wrapper declares the same values explicitly without changing the body.
    variables = re.sub(
        r"^\s*uniform\s+(?:vec2|mat4)\s+(?:u_model_size|u_transform);\s*$",
        "",
        variables,
        flags=re.MULTILINE,
    )
    functions = _extract("fragment_functions").replace("texture2D", "texture")
    body = body.replace("texture2D", "texture")
    body = body.replace(
        "vec4 source = gl_FragColor;",
        "vec4 source = texture(tex0, v_tex_coord, u_lod_bias);",
        1,
    )
    body = body.replace("gl_FragColor", "fragColor")
    return f"""#version 330 core
uniform sampler2D tex0;
uniform float u_lod_bias;
in vec2 v_tex_coord;
{variables}
out vec4 fragColor;

{functions}

void main() {{
{body}
}}
"""


def transport_blend_fragment_source() -> str:
    variables = _extract("transport_blend_variables").replace("varying ", "in ")
    body = _extract("transport_blend_fragment").replace("texture2D", "texture")
    body = body.replace("gl_FragColor", "fragColor")
    return (
        "#version 330 core\n"
        + variables
        + "\nout vec4 fragColor;\nvoid main() {\n"
        + body
        + "\n}\n"
    )


def live_probe_fragment_source() -> str:
    variables = _extract("live_probe_variables").replace("varying ", "in ")
    body = _extract("live_probe_fragment").replace("texture2D", "texture")
    body = body.replace("gl_FragColor", "fragColor")
    return (
        "#version 330 core\n"
        + variables
        + "\nout vec4 fragColor;\nvoid main() {\n"
        + body
        + "\n}\n"
    )


def color_glow_fragment_source(stage: str = "composite") -> str:
    if stage not in {"composite", "mask", "blur"}:
        raise ValueError("Unknown selective glow shader stage")
    prefix = "color_glow_blur" if stage == "blur" else "color_glow"
    body_prefix = "color_glow" if stage == "composite" else f"color_glow_{stage}"
    variables = _extract(prefix + "_variables").replace("varying ", "in ")
    functions = _extract(prefix + "_functions").replace("texture2D", "texture")
    body = _extract(body_prefix + "_fragment").replace("texture2D", "texture")
    return (
        "#version 330 core\n"
        + variables
        + "\nout vec4 fragColor;\n"
        + functions
        + "\nvoid main() {\n"
        + body.replace("gl_FragColor", "fragColor")
        + "\n}\n"
    )


BACKGROUND_VERTEX = """#version 330 core
in vec2 in_unit;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    gl_Position = vec4(in_unit.x * 2.0 - 1.0, 1.0 - in_unit.y * 2.0, 0.0, 1.0);
    v_uv = in_uv;
}
"""

BACKGROUND_FRAGMENT = """#version 330 core
uniform sampler2D background_texture;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    fragColor = texture(background_texture, v_uv);
}
"""
