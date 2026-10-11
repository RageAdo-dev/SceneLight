"""Trusted multi-layer VFX shader presets used by declarative effect packs."""

from __future__ import annotations


def _float(default: float, minimum: float, maximum: float, label: str) -> dict[str, object]:
    return {
        "type": "float",
        "default": default,
        "min": minimum,
        "max": maximum,
        "label": label,
    }


def _vec2(
    default: tuple[float, float],
    minimum: float,
    maximum: float,
    label: str,
) -> dict[str, object]:
    return {
        "type": "vec2",
        "default": list(default),
        "min": minimum,
        "max": maximum,
        "label": label,
    }


def _vec3(
    default: tuple[float, float, float],
    minimum: float,
    maximum: float,
    label: str,
) -> dict[str, object]:
    return {
        "type": "vec3",
        "default": list(default),
        "min": minimum,
        "max": maximum,
        "label": label,
    }


_NOISE_FUNCTIONS = """
float l__hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float l__noise21(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = l__hash21(i);
    float b = l__hash21(i + vec2(1.0, 0.0));
    float c = l__hash21(i + vec2(0.0, 1.0));
    float d = l__hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float l__fbm21(vec2 p) {
    float value = 0.0;
    value += 0.5000 * l__noise21(p); p = p * 2.03 + vec2(13.1, 7.7);
    value += 0.2500 * l__noise21(p); p = p * 2.01 + vec2(5.3, 17.9);
    value += 0.1250 * l__noise21(p); p = p * 2.04 + vec2(19.7, 3.1);
    value += 0.0625 * l__noise21(p);
    return value / 0.9375;
}

float l__sd_segment(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a;
    vec2 ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 0.00001), 0.0, 1.0);
    return length(pa - ba * h);
}
"""


_LIGHTNING_FUNCTIONS = (
    _NOISE_FUNCTIONS
    + """
float l__lightning_path(vec2 p, float time, float seed, float center, float width) {
    float x0 = center + (l__noise21(vec2(seed + 0.0, time * 2.1)) - 0.5) * width;
    float x1 = center + (l__noise21(vec2(seed + 7.3, time * 2.3)) - 0.5) * width;
    float x2 = center + (l__noise21(vec2(seed + 14.6, time * 2.5)) - 0.5) * width;
    float x3 = center + (l__noise21(vec2(seed + 21.9, time * 2.7)) - 0.5) * width;
    float x4 = center + (l__noise21(vec2(seed + 29.2, time * 2.9)) - 0.5) * width;
    float x5 = center + (l__noise21(vec2(seed + 36.5, time * 3.1)) - 0.5) * width;
    float x6 = center + (l__noise21(vec2(seed + 43.8, time * 3.3)) - 0.5) * width;
    float distance_value = l__sd_segment(p, vec2(x0, 0.0), vec2(x1, 0.17));
    distance_value = min(distance_value, l__sd_segment(p, vec2(x1, 0.17), vec2(x2, 0.34)));
    distance_value = min(distance_value, l__sd_segment(p, vec2(x2, 0.34), vec2(x3, 0.50)));
    distance_value = min(distance_value, l__sd_segment(p, vec2(x3, 0.50), vec2(x4, 0.67)));
    distance_value = min(distance_value, l__sd_segment(p, vec2(x4, 0.67), vec2(x5, 0.84)));
    distance_value = min(distance_value, l__sd_segment(p, vec2(x5, 0.84), vec2(x6, 1.0)));
    float branch_x = x3 + (l__noise21(vec2(seed + 61.0, time * 3.7)) - 0.5) * width * 1.4;
    distance_value = min(distance_value, l__sd_segment(p, vec2(x3, 0.50), vec2(branch_x, 0.72)));
    return distance_value;
}
"""
)


VFX_PRESETS: dict[str, dict[str, object]] = {
    "lightning_god": {
        "parameters": {
            "intensity": _float(0.0, 0.0, 1.0, "Intensity"),
            "speed": _float(1.0, 0.0, 5.0, "Speed"),
            "aura_size": _float(0.032, 0.012, 0.08, "Aura size"),
            "discharge": _float(0.85, 0.0, 1.5, "Discharge"),
            "aura_color": _vec3((0.04, 0.46, 1.0), 0.0, 1.5, "Aura color"),
            "core_color": _vec3((0.76, 0.94, 1.0), 0.0, 1.5, "Core color"),
        },
        "functions": _LIGHTNING_FUNCTIONS,
        "fragment": """
vec2 l__uv = v_tex_coord;
vec4 l__base = texture2D(tex0, l__uv);
float l__r = u__aura_size;
float l__blur = 0.0;
l__blur += texture2D(tex0, clamp(l__uv + vec2( l__r, 0.0), 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2(-l__r, 0.0), 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2(0.0,  l__r), 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2(0.0, -l__r), 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2( l__r,  l__r) * 0.72, 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2(-l__r,  l__r) * 0.72, 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2( l__r, -l__r) * 0.72, 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2(-l__r, -l__r) * 0.72, 0.001, 0.999)).a;
l__blur *= 0.125;
float l__storm = l__fbm21(l__uv * vec2(7.0, 10.0) + vec2(u_time * u__speed, -u_time * 1.7));
float l__aura = smoothstep(0.055, 0.66, l__blur) * (1.0 - smoothstep(0.05, 0.82, l__base.a));
l__aura *= 0.22 + 1.05 * smoothstep(0.28, 0.76, l__storm);
float l__time = u_time * u__speed;
float l__d1 = l__lightning_path(l__uv, l__time, 3.1, 0.17, 0.23);
float l__d2 = l__lightning_path(l__uv, -l__time, 19.7, 0.83, 0.23);
float l__d3 = l__lightning_path(l__uv, l__time * 1.23, 41.3, 0.50, 0.46);
float l__core = max(1.0 - smoothstep(0.0012, 0.0042, l__d1), max(1.0 - smoothstep(0.0012, 0.0042, l__d2), 1.0 - smoothstep(0.0008, 0.0030, l__d3)));
float l__glow = max(1.0 - smoothstep(0.003, 0.032, l__d1), max(1.0 - smoothstep(0.003, 0.032, l__d2), 1.0 - smoothstep(0.002, 0.024, l__d3)));
float l__flash = 0.18 + 0.82 * smoothstep(0.22, 0.82, l__noise21(vec2(floor(l__time * 5.0), 73.0)));
l__core *= l__flash * u__discharge;
l__glow *= l__flash * u__discharge;
float l__sparks = 0.0;
for (int l__i = 0; l__i < 18; l__i++) {
    float l__fi = float(l__i);
    float l__seed = l__hash21(vec2(l__fi * 7.31, l__fi * 19.17));
    float l__life = fract(l__time * (0.32 + l__seed * 0.24) + l__seed);
    vec2 l__position = vec2(0.18 + 0.64 * l__hash21(vec2(l__fi, 8.7)), 0.94 - l__life * 0.92);
    l__position.x += sin(l__life * 12.0 + l__seed * 19.0) * (0.025 + l__seed * 0.045);
    float l__distance = length((l__uv - l__position) * vec2(1.0, 0.82));
    float l__particle = exp(-l__distance * l__distance * (18000.0 + l__seed * 22000.0));
    l__sparks += l__particle * sin(3.14159 * l__life);
}
l__sparks = clamp(l__sparks, 0.0, 1.0) * u__discharge;
vec4 l__out = l__base;
l__out.rgb += u__aura_color * l__aura * 0.78;
l__out.rgb += u__aura_color * (l__glow * 0.72 + l__sparks * 0.55) + u__core_color * l__core;
l__out.rgb = mix(l__out.rgb, l__out.rgb + u__core_color * 0.16, l__base.a * (l__aura + l__glow));
l__out.a = max(l__base.a, max(l__aura * 0.72, max(l__glow * 0.72, max(l__core, l__sparks * 0.75))));
gl_FragColor = mix(gl_FragColor, l__out, u__intensity);
""",
    },
    "inferno_incarnate": {
        "parameters": {
            "intensity": _float(0.0, 0.0, 1.0, "Intensity"),
            "speed": _float(0.85, 0.0, 4.0, "Speed"),
            "height": _float(0.17, 0.04, 0.3, "Flame height"),
            "turbulence": _float(1.0, 0.0, 2.0, "Turbulence"),
            "outer_color": _vec3((0.72, 0.015, 0.0), 0.0, 1.5, "Outer flame"),
            "core_color": _vec3((1.0, 0.68, 0.06), 0.0, 1.5, "Flame core"),
        },
        "functions": _NOISE_FUNCTIONS,
        "fragment": """
vec2 l__uv = v_tex_coord;
vec4 l__base = texture2D(tex0, l__uv);
float l__time = u_time * u__speed;
float l__flow = l__fbm21(vec2(l__uv.x * 8.0, l__uv.y * 6.0 - l__time * 2.4));
float l__fine = l__fbm21(vec2(l__uv.x * 18.0 + l__time * 0.7, l__uv.y * 13.0 - l__time * 3.8));
float l__detail = l__fbm21(vec2(l__uv.x * 33.0 - l__time * 0.4, l__uv.y * 25.0 - l__time * 5.2));
float l__warp = (l__flow - 0.5) * 0.052 * u__turbulence;
float l__a1 = texture2D(tex0, clamp(l__uv + vec2(l__warp * 0.35, u__height * 0.10), 0.001, 0.999)).a;
float l__a2 = texture2D(tex0, clamp(l__uv + vec2(-l__warp * 0.58, u__height * 0.24), 0.001, 0.999)).a;
float l__a3 = texture2D(tex0, clamp(l__uv + vec2(l__warp * 0.92, u__height * 0.42), 0.001, 0.999)).a;
float l__a4 = texture2D(tex0, clamp(l__uv + vec2(-l__warp * 1.26, u__height * 0.63), 0.001, 0.999)).a;
float l__a5 = texture2D(tex0, clamp(l__uv + vec2(l__warp * 1.62, u__height * 0.82), 0.001, 0.999)).a;
float l__a6 = texture2D(tex0, clamp(l__uv + vec2(-l__warp * 1.95, u__height), 0.001, 0.999)).a;
float l__n1 = smoothstep(0.22, 0.62, l__flow * 0.62 + l__fine * 0.38);
float l__n2 = smoothstep(0.30, 0.68, l__flow * 0.45 + l__detail * 0.55);
float l__n3 = smoothstep(0.40, 0.73, l__fine * 0.52 + l__detail * 0.48);
float l__core_flame = max(l__a1 * l__n1, l__a2 * l__n1 * 0.92);
float l__mid_flame = max(l__a3 * l__n2 * 0.86, l__a4 * l__n2 * 0.74);
float l__outer_flame = max(l__a5 * l__n3 * 0.62, l__a6 * l__n3 * 0.48);
float l__flame = max(l__core_flame, max(l__mid_flame, l__outer_flame));
float l__outside = 1.0 - smoothstep(0.06, 0.76, l__base.a);
l__flame *= l__outside;
vec3 l__flame_color = u__outer_color * l__outer_flame;
l__flame_color += vec3(1.0, 0.16, 0.01) * l__mid_flame;
l__flame_color += u__core_color * l__core_flame;
l__flame_color *= l__outside;
float l__ember = 0.0;
float l__ember_glow = 0.0;
for (int l__i = 0; l__i < 24; l__i++) {
    float l__fi = float(l__i);
    float l__seed = l__hash21(vec2(l__fi * 11.17, l__fi * 3.73));
    float l__life = fract(l__time * (0.22 + l__seed * 0.18) + l__seed);
    vec2 l__position = vec2(0.20 + 0.60 * l__hash21(vec2(l__fi, 91.7)), 1.02 - l__life * 1.02);
    l__position.x += sin(l__life * (7.0 + l__seed * 6.0) + l__seed * 23.0) * (0.025 + l__seed * 0.055);
    float l__distance = length((l__uv - l__position) * vec2(1.0, 0.82));
    float l__point = exp(-l__distance * l__distance * (13000.0 + l__seed * 18000.0));
    float l__trail_distance = l__sd_segment(l__uv, l__position, l__position + vec2(0.0, 0.035 + l__seed * 0.05));
    float l__trail = exp(-l__trail_distance * l__trail_distance * 18000.0) * smoothstep(0.08, 0.42, l__life);
    float l__fade = sin(3.14159 * l__life);
    l__ember += l__point * l__fade;
    l__ember_glow += l__trail * l__fade * 0.45;
}
l__ember = clamp(l__ember, 0.0, 1.0);
l__ember_glow = clamp(l__ember_glow, 0.0, 1.0);
vec4 l__out = l__base;
l__out.rgb = mix(l__out.rgb, l__out.rgb * vec3(1.0, 0.58, 0.22), l__base.a * 0.30);
l__out.rgb += l__flame_color * 0.92 + u__core_color * (l__ember + l__ember_glow * 0.52);
l__out.a = max(l__base.a, max(l__flame * 0.78, max(l__ember, l__ember_glow * 0.68)));
gl_FragColor = mix(gl_FragColor, l__out, u__intensity);
""",
    },
    "the_legend": {
        "parameters": {
            "intensity": _float(0.0, 0.0, 1.0, "Intensity"),
            "speed": _float(0.65, 0.0, 4.0, "Speed"),
            "aura_size": _float(0.052, 0.018, 0.12, "Aura size"),
            "surge": _float(1.0, 0.0, 1.5, "Surge"),
            "aura_color": _vec3((0.20, 0.95, 0.025), 0.0, 1.5, "Aura color"),
            "core_color": _vec3((0.72, 1.0, 0.18), 0.0, 1.5, "Core color"),
        },
        "functions": _NOISE_FUNCTIONS,
        "fragment": """
vec2 l__uv = v_tex_coord;
vec4 l__base = texture2D(tex0, l__uv);
float l__r = u__aura_size;
float l__blur = 0.0;
l__blur += texture2D(tex0, clamp(l__uv + vec2( l__r, 0.0), 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2(-l__r, 0.0), 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2(0.0,  l__r), 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2(0.0, -l__r), 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2( l__r,  l__r) * 0.72, 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2(-l__r,  l__r) * 0.72, 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2( l__r, -l__r) * 0.72, 0.001, 0.999)).a;
l__blur += texture2D(tex0, clamp(l__uv + vec2(-l__r, -l__r) * 0.72, 0.001, 0.999)).a;
l__blur *= 0.125;
float l__flow = l__fbm21(vec2(l__uv.x * 8.0, l__uv.y * 6.0 - u_time * u__speed * 2.5));
float l__aura = smoothstep(0.04, 0.58, l__blur) * (1.0 - smoothstep(0.08, 0.78, l__base.a));
l__aura *= 0.16 + 1.12 * smoothstep(0.24, 0.74, l__flow);
float l__pillar_noise = l__fbm21(vec2(l__uv.x * 23.0, -u_time * u__speed * 3.0));
float l__pillars = pow(l__pillar_noise, 5.0) * smoothstep(0.98, 0.12, l__uv.y);
float l__radial = length((l__uv - vec2(0.5, 0.55)) * vec2(1.0, 0.74));
float l__ring_phase = fract(u_time * u__speed * 0.58);
float l__ring_radius = mix(0.12, 0.78, l__ring_phase);
float l__ring = (1.0 - smoothstep(0.008, 0.026, abs(l__radial - l__ring_radius))) * (1.0 - l__ring_phase);
float l__edge_energy = l__aura * (0.58 + 0.58 * l__fbm21(vec2(l__uv.x * 16.0, l__uv.y * 10.0 - u_time * u__speed * 3.6)));
float l__field = max(l__edge_energy, max(l__pillars * 0.34, l__ring * 0.42));
float l__particles = 0.0;
float l__particle_trails = 0.0;
for (int l__i = 0; l__i < 22; l__i++) {
    float l__fi = float(l__i);
    float l__seed = l__hash21(vec2(l__fi * 5.17, l__fi * 13.91));
    float l__life = fract(u_time * u__speed * (0.18 + l__seed * 0.16) + l__seed);
    vec2 l__position = vec2(0.18 + 0.64 * l__hash21(vec2(l__fi, 47.2)), 1.0 - l__life * 1.04);
    l__position.x += sin(l__life * 8.0 + l__seed * 31.0) * (0.018 + l__seed * 0.04);
    float l__distance = length((l__uv - l__position) * vec2(1.0, 0.78));
    float l__point = exp(-l__distance * l__distance * (9000.0 + l__seed * 19000.0));
    float l__trail_distance = l__sd_segment(l__uv, l__position, l__position + vec2(0.0, 0.045 + l__seed * 0.07));
    float l__trail = exp(-l__trail_distance * l__trail_distance * 12000.0);
    float l__fade = sin(3.14159 * l__life);
    l__particles += l__point * l__fade;
    l__particle_trails += l__trail * l__fade * 0.35;
}
l__particles = clamp(l__particles, 0.0, 1.0);
l__particle_trails = clamp(l__particle_trails, 0.0, 1.0);
vec4 l__out = l__base;
l__out.rgb = mix(l__out.rgb, l__out.rgb * vec3(0.76, 1.10, 0.54), l__base.a * 0.32);
l__out.rgb += u__aura_color * (l__field * 0.82 + l__particle_trails * 0.52) * u__surge;
l__out.rgb += u__core_color * (l__aura * (0.18 + 0.24 * l__flow) + l__particles) * u__surge;
l__out.a = max(l__base.a, max(l__field * 0.78, max(l__particles, l__particle_trails * 0.68)));
gl_FragColor = mix(gl_FragColor, l__out, u__intensity);
""",
    },
    "eyes_everywhere": {
        "parameters": {
            "intensity": _float(0.0, 0.0, 1.0, "Intensity"),
            "density": _float(11.0, 5.0, 22.0, "Eye density"),
            "speed": _float(0.7, 0.0, 5.0, "Look speed"),
            "eye_center": _vec2((0.39, 0.33), 0.0, 1.0, "Source eye center"),
            "eye_size": _vec2((0.085, 0.055), 0.005, 0.35, "Source eye size"),
            "flesh_color": _vec3((0.24, 0.015, 0.045), 0.0, 1.0, "Flesh color"),
        },
        "functions": _NOISE_FUNCTIONS,
        "fragment": """
vec4 l__base = texture2D(tex0, v_tex_coord);
float l__rows = u__density * 1.18;
float l__row = floor(v_tex_coord.y * l__rows);
float l__stagger = mod(l__row, 2.0) * 0.5;
vec2 l__grid_uv = vec2(v_tex_coord.x * u__density + l__stagger, v_tex_coord.y * l__rows);
vec2 l__cell = floor(l__grid_uv);
vec2 l__local = fract(l__grid_uv) - 0.5;
float l__hash = l__hash21(l__cell);
float l__present = step(0.10, l__hash);
float l__size = mix(0.70, 1.24, l__hash21(l__cell + 19.7));
float l__phase = u_time * u__speed + l__hash * 17.0;
float l__blink_wave = sin(l__phase * 0.73 + floor(l__phase * 0.19) * 4.7);
float l__blink = mix(1.0, 0.10, smoothstep(0.91, 0.985, l__blink_wave));
vec2 l__look = vec2(sin(l__phase * 1.7), cos(l__phase * 1.23)) * vec2(0.12, 0.08);
vec2 l__warped = l__local;
l__warped.x += sin(l__local.y * 8.0 + l__phase) * 0.018;
l__warped.y += sin(l__local.x * 7.0 - l__phase * 0.6) * 0.012;
vec2 l__eye_p = vec2(l__warped.x, l__warped.y * 1.62 / l__blink) / l__size;
float l__eye = (1.0 - smoothstep(0.34, 0.47, length(l__eye_p))) * l__present * l__base.a;
float l__inner = (1.0 - smoothstep(0.29, 0.39, length(l__eye_p))) * l__present * l__base.a;
float l__rim = max(0.0, l__eye - l__inner);
float l__flip = step(0.5, l__hash21(l__cell + 7.1)) * -2.0 + 1.0;
vec2 l__sample_local = vec2(l__warped.x * l__flip, l__warped.y / l__blink) / l__size;
vec2 l__sample_uv = u__eye_center + (l__sample_local + l__look) * u__eye_size;
vec4 l__actual_eye = texture2D(tex0, clamp(l__sample_uv, 0.001, 0.999));
float l__vein = pow(l__fbm21(l__cell * 3.0 + l__local * 13.0 + u_time * 0.08), 6.0) * l__rim;
vec3 l__skin = mix(l__base.rgb * vec3(0.38, 0.10, 0.16), u__flesh_color * l__base.a, 0.46);
l__skin = mix(l__skin, l__actual_eye.rgb, l__inner * l__actual_eye.a);
l__skin += u__flesh_color * l__rim * 1.15 + vec3(0.45, 0.0, 0.02) * l__vein;
vec4 l__out = vec4(l__skin, l__base.a);
gl_FragColor = mix(gl_FragColor, l__out, u__intensity);
""",
    },
}
