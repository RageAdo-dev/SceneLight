"""Move constant scene samples to vertices without changing the lighting math.

Shared by the desktop preview and Ren'Py 7/8 (Python 2 compatible). The inputs
remain the production shader strings; this module does not duplicate its helpers.
"""

import re

ORIGINAL = "scenelight.dynamic_sprite"
OPTIMIZED = "scenelight.dynamic_sprite_vertex"


def supported(varying_components, vertex_samplers):
    # 24 packed outputs plus three coordinate vectors and one spare vec4.
    # Compatibility GL reports 124 rather than 128 on some drivers. Additional
    # game shader parts are checked by linking their actual combined sources.
    return varying_components >= 28 * 4 and vertex_samplers >= 4


def build(functions, body):
    """Return variables, vertex helpers/body, and the modified fragment body."""
    helpers = []
    for name in (
        "scenelight_field_uv",
        "scenelight_atlas_uv",
        "scenelight_scene_at",
        "scenelight_wrap_at",
        "scenelight_transport_at",
    ):
        match = re.search(r"\bvec[234] " + name + r"\(.*?\n\s*}", functions, re.S)
        if match is None:
            raise ValueError("Missing production helper: " + name)
        helpers.append(match.group())

    packed = ["v_sc_pack_%d" % i for i in range(20)]
    declarations = ["varying vec4 %s;" % name for name in packed]
    declarations += [
        "varying vec4 v_sc_" + name + ";"
        for name in (
            "irradiance",
            "emitter",
            "gradient",
        )
    ]
    declarations.append("varying vec3 v_sc_wrap;")
    statements, components = [], []
    for plane in range(26):
        name = "sc_vertex_transport_%d" % plane
        statements.append(
            "vec3 %s = scenelight_transport_at(%d.0, v_sc_center).rgb;" % (name, plane)
        )
        components.extend(name + "." + channel for channel in "rgb")
    components.extend(("0.0", "0.0"))
    statements.extend(
        "%s = vec4(%s);" % (name, ", ".join(components[i * 4 : i * 4 + 4]))
        for i, name in enumerate(packed)
    )

    def transport(match):
        plane = int(match.group(1))
        if plane >= 26:
            raise ValueError("Unexpected transport plane")
        channels = [
            packed[(plane * 3 + j) // 4] + "." + "xyzw"[(plane * 3 + j) % 4] for j in range(3)
        ]
        return "vec4(vec3(%s), 1.0)" % ", ".join(channels)

    body, count = re.subn(r"scenelight_transport_at\((\d+)\.0,\s*v_sc_center\)", transport, body)
    if count != 26:
        raise ValueError("Production transport layout changed")
    statements.append("""
        v_sc_irradiance = scenelight_scene_at(tex1, v_sc_center);
        v_sc_emitter = scenelight_scene_at(tex2, v_sc_center);
        vec2 sc_vertex_dx = vec2(u_sc_atlas_texel.x / u_sc_scene_uv.z * 1.5, 0.0);
        vec2 sc_vertex_dy = vec2(0.0, u_sc_atlas_texel.y / u_sc_scene_uv.w * 1.5);
        v_sc_gradient = vec4(
            scenelight_scene_at(tex2, v_sc_center - sc_vertex_dx).a,
            scenelight_scene_at(tex2, v_sc_center + sc_vertex_dx).a,
            scenelight_scene_at(tex2, v_sc_center - sc_vertex_dy).a,
            scenelight_scene_at(tex2, v_sc_center + sc_vertex_dy).a);
        v_sc_wrap = scenelight_wrap_at(v_sc_center);
    """)
    replacements = [
        ("scenelight_scene_at(tex1, v_sc_center)", "v_sc_irradiance"),
        ("scenelight_scene_at(tex2, v_sc_center)", "v_sc_emitter"),
        ("scenelight_wrap_at(v_sc_center)", "v_sc_wrap"),
    ]
    for expression, channel in (
        ("- screen_dx", "x"),
        ("+ screen_dx", "y"),
        ("- screen_dy", "z"),
        ("+ screen_dy", "w"),
    ):
        replacements.append(
            ("scenelight_emitter_at(v_sc_center " + expression + ")", "v_sc_gradient." + channel)
        )
    for old, new in replacements:
        if old not in body:
            raise ValueError("Production center sampling changed: " + old)
        body = body.replace(old, new)
    return "\n".join(declarations), "\n".join(helpers), "\n".join(statements), body


def vertex_preamble(variables, helpers, body):
    """Keep helper uniforms visible on both old and new Ren'Py assemblers.

    Older engines emit functions before automatic declarations and discover
    dependencies only in numbered bodies. Declare these uniforms explicitly,
    using aliases so the assembler cannot declare them a second time.
    """
    # Ren'Py 7 assigns another texture unit for a duplicate sampler declaration.
    # These samplers already have fragment declarations. Let GLSL see them here
    # without making that scanner count them twice and shift tex0's res0 unit.
    declarations = ["#define SC_VERTEX_SAMPLER uniform sampler2D"]
    for kind, name in re.findall(r"uniform\s+(\w+)\s+(\w+);", variables):
        if not re.search(r"\b" + name + r"\b", helpers + body):
            continue
        alias = "sc_vertex_" + name
        helpers = re.sub(r"\b" + name + r"\b", alias, helpers)
        body = re.sub(r"\b" + name + r"\b", alias, body)
        declaration = (
            "SC_VERTEX_SAMPLER %s;" % name
            if kind == "sampler2D"
            else "uniform %s %s;" % (kind, name)
        )
        declarations.extend((declaration, "#define %s %s" % (alias, name)))
    # The engine concatenates its first attribute declaration immediately after
    # this string. Its line-based attribute scanner needs a separating newline.
    return "\n".join(declarations) + "\n" + helpers + "\n", body
