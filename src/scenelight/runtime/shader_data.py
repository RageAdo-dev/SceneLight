"""Shared production GLSL, loaded by Ren'Py 7/8 and Preview (Python 2 compatible)."""

SHADERS = {
    "live_probe_variables": """
        uniform sampler2D tex1;
        uniform vec2 u_sc_probe_grid;
        varying vec2 v_tex_coord;
    """,
    "live_probe_fragment": """
        vec3 total = vec3(0.0);
        for (int y = 0; y < 4; y++) {
            for (int x = 0; x < 4; x++) {
                vec2 offset = (vec2(float(x), float(y)) - vec2(1.5))
                    / (u_sc_probe_grid * 4.0);
                vec3 color = texture2D(tex1, clamp(v_tex_coord + offset,
                    vec2(0.0), vec2(1.0))).rgb;
                vec3 low = color / 12.92;
                vec3 high = pow((color + vec3(0.055)) / 1.055, vec3(2.4));
                total += mix(low, high, step(vec3(0.04045), color));
            }
        }
        gl_FragColor = vec4(total / 16.0, 1.0);
    """,
    "transport_blend_variables": """
        uniform sampler2D tex1;
        uniform vec4 u_sc_field_left;
        uniform vec4 u_sc_field_right;
        uniform float u_sc_field_amount;
        uniform float u_sc_field_layout_change;
        varying vec2 v_tex_coord;
    """,
    "transport_blend_fragment": """
        vec4 left_value = texture2D(tex1,
            u_sc_field_left.xy + v_tex_coord * u_sc_field_left.zw);
        vec4 right_value = texture2D(tex1,
            u_sc_field_right.xy + v_tex_coord * u_sc_field_right.zw);
        vec3 value = mix(left_value.rgb, right_value.rgb, u_sc_field_amount);
        float plane = floor(v_tex_coord.x * 26.0);
        if (u_sc_field_layout_change > 0.5 && plane >= 6.0 && plane < 15.0) {
            value = u_sc_field_amount < 0.5 ? left_value.rgb : right_value.rgb;
            if (mod(plane, 3.0) > 1.5) {
                float phase = u_sc_field_amount < 0.5
                    ? 1.0 - u_sc_field_amount * 2.0
                    : u_sc_field_amount * 2.0 - 1.0;
                value *= smoothstep(0.0, 1.0, phase);
            }
        }
        // Quantize each field texel before the sprite samples it bilinearly,
        // matching the reference's round-to-nearest/even data contract.
        vec3 scaled = value * 255.0;
        vec3 integral = floor(scaled);
        vec3 fraction = scaled - integral;
        vec3 rounded = floor(scaled + 0.5);
        rounded = mix(rounded, integral + mod(integral, 2.0),
            vec3(equal(fraction, vec3(0.5))));
        gl_FragColor = vec4(rounded / 255.0, 1.0);
    """,
    "color_glow_variables": """
        uniform sampler2D tex0;
        uniform sampler2D tex1;
        uniform sampler2D tex2;
        uniform vec3 u_sc_rule_color;
        uniform vec4 u_sc_rule_data;
        uniform vec2 u_sc_rule_size;
        uniform float u_sc_rule_compare;
        varying vec2 v_tex_coord;
    """,
    "color_glow_functions": """
        vec3 scenelight_rule_hsv(vec3 color) {
            vec4 k = vec4(0.0, -1.0/3.0, 2.0/3.0, -1.0);
            vec4 p = mix(vec4(color.bg, k.wz), vec4(color.gb, k.xy), step(color.b, color.g));
            vec4 q = mix(vec4(p.xyw, color.r), vec4(color.r, p.yzx), step(p.x, color.r));
            float delta = q.x - min(q.w, q.y);
            return vec3(abs(q.z + (q.w-q.y)/(6.0*delta+0.00001)),
                        delta/(q.x+0.00001), q.x);
        }
        vec4 scenelight_rule_sample(vec4 sample_color, vec3 target_color, vec4 rule) {
            if (sample_color.a <= 0.001) return vec4(0.0);
            vec3 color = clamp(sample_color.rgb / sample_color.a, 0.0, 1.0);
            vec3 hsv = scenelight_rule_hsv(color);
            vec3 target = scenelight_rule_hsv(target_color);
            float hue = abs(hsv.x-target.x);
            hue = min(hue, 1.0-hue)*2.0;
            float chromatic = hue * sqrt(hsv.y*target.y)
                + 0.25*abs(hsv.y-target.y) + 0.03*abs(hsv.z-target.z);
            float neutral = length(color-target_color)/1.7320508;
            float distance = mix(neutral, chromatic, smoothstep(0.02, 0.12, target.y));
            float selection = 1.0 - smoothstep(rule.z,
                rule.z + max(0.0001, rule.w), distance);
            return sample_color * selection;
        }
    """,
    "color_glow_fragment": """
        vec4 base = texture2D(tex0, v_tex_coord);
        float shown = 1.0 - step(0.5, u_sc_rule_compare)
            + step(1.5, u_sc_rule_compare) * step(0.5, v_tex_coord.x);
        float strength = u_sc_rule_data.x * shown;
        vec4 selected = scenelight_rule_sample(texture2D(tex1, v_tex_coord), u_sc_rule_color, u_sc_rule_data);
        vec4 blurred = vec4(0.0);
        if (u_sc_rule_data.y > 0.0 && strength > 0.0) {
            blurred = texture2D(tex2, v_tex_coord);
        }
        float halo_alpha = 1.0 - exp(-blurred.a * strength * 1.8);
        float alpha = max(base.a, halo_alpha);
        vec3 added = selected.rgb * (0.65 * strength) + blurred.rgb * (0.8 * strength);
        gl_FragColor = vec4(min(base.rgb + added, vec3(alpha)), alpha);
    """,
    "color_glow_mask_fragment": """
        gl_FragColor = scenelight_rule_sample(texture2D(tex0, v_tex_coord), u_sc_rule_color, u_sc_rule_data);
    """,
    "color_glow_blur_variables": """
        uniform sampler2D tex0;
        uniform vec2 u_sc_rule_step;
        varying vec2 v_tex_coord;
    """,
    "color_glow_blur_functions": """
        vec4 scenelight_rule_blur_sample(sampler2D source_texture, vec2 uv) {
            if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) return vec4(0.0);
            return texture2D(source_texture, uv);
        }
    """,
    "color_glow_blur_fragment": """
        vec4 blurred = texture2D(tex0, v_tex_coord) * 0.2270270270;
        blurred += (scenelight_rule_blur_sample(tex0, v_tex_coord + u_sc_rule_step)
                  + scenelight_rule_blur_sample(tex0, v_tex_coord - u_sc_rule_step)) * 0.1945945946;
        blurred += (scenelight_rule_blur_sample(tex0, v_tex_coord + u_sc_rule_step * 2.0)
                  + scenelight_rule_blur_sample(tex0, v_tex_coord - u_sc_rule_step * 2.0)) * 0.1216216216;
        blurred += (scenelight_rule_blur_sample(tex0, v_tex_coord + u_sc_rule_step * 3.0)
                  + scenelight_rule_blur_sample(tex0, v_tex_coord - u_sc_rule_step * 3.0)) * 0.0540540541;
        blurred += (scenelight_rule_blur_sample(tex0, v_tex_coord + u_sc_rule_step * 4.0)
                  + scenelight_rule_blur_sample(tex0, v_tex_coord - u_sc_rule_step * 4.0)) * 0.0162162162;
        gl_FragColor = blurred;
    """,
    "variables": """
            uniform vec4 u_sc_wrap_uv;
            uniform vec4 u_sc_wrap_uv_next;
            uniform vec2 u_sc_wrap_texel;
            uniform float u_sc_wrap_blend;
            uniform sampler2D tex1;
            uniform sampler2D tex2;
            uniform sampler2D tex3;
            uniform sampler2D tex4;
            uniform sampler2D tex5;
            uniform sampler2D tex6;
            uniform sampler2D tex7;
            uniform vec2 u_sc_sprite_size;
            uniform vec2 u_model_size;
            uniform mat4 u_transform;
            uniform vec4 u_sc_scene_uv;
            uniform vec4 u_sc_scene_uv_next;
            uniform float u_sc_scene_blend;
            uniform vec2 u_sc_atlas_texel;
            uniform float u_sc_reference_mid;
            uniform float u_sc_strength;
            uniform float u_sc_authored_grade;
            uniform float u_sc_exposure_owner;
            uniform float u_sc_exposure_bias_owner;
            uniform float u_sc_exposure_auto;
            uniform float u_sc_exposure_bias;
            uniform float u_sc_chroma_range;
            uniform float u_sc_target_range;
            uniform vec3 u_sc_shadow_chroma;
            uniform float u_sc_local_saturation;
            uniform float u_sc_local_contrast;
            uniform float u_sc_light_confidence;
            uniform float u_sc_source_size;
            uniform float u_sc_grain;
            uniform float u_sc_sharpness;
            uniform float u_sc_has_form;
            uniform vec2 u_sc_form_center;
            uniform vec3 u_sc_group_anchor;
            uniform vec4 u_sc_snapshot_rect;
            uniform float u_sc_use_snapshot_rect;
            uniform float u_sc_mean_form_visibility;
            uniform float u_sc_form_contrast_mid;
            uniform vec2 u_sc_height_range;
            uniform float u_sc_noise_range;
            uniform float u_sc_local_luminance;
            uniform float u_sc_has_transport;
            uniform float u_sc_live_background;
            uniform float u_sc_live_analysis;
            uniform vec4 u_sc_transport_uv;
            uniform vec2 u_sc_transport_grid;
            uniform float u_sc_transport_subject_y_max;
            uniform float u_sc_debug_contrast;
            uniform float u_sc_compare_mode;
            uniform float u_sc_effect_time;
            uniform vec4 u_sc_rain_data;
            uniform vec4 u_sc_rain_color_scale;
            uniform vec4 u_sc_glitch_data;
            uniform vec4 u_sc_glitch_extra;
            uniform vec4 u_sc_calibration0;
            uniform vec4 u_sc_calibration1;
            uniform vec4 u_sc_calibration2;
            uniform vec4 u_sc_calibration3;
            uniform vec4 u_sc_calibration4;
            uniform vec4 u_sc_calibration8;
            uniform vec2 u_sc_glow_data;
            uniform vec4 u_sc_glow_color;
            uniform float u_sc_screen_aspect;
            uniform vec4 u_sc_sprite_light0_data;
            uniform vec3 u_sc_sprite_light0_color;
            uniform vec4 u_sc_sprite_light1_data;
            uniform vec3 u_sc_sprite_light1_color;
            uniform vec4 u_sc_sprite_light2_data;
            uniform vec3 u_sc_sprite_light2_color;
            uniform vec4 u_sc_sprite_light3_data;
            uniform vec3 u_sc_sprite_light3_color;
            uniform vec4 u_sc_light0_data;
            uniform vec4 u_sc_light0_color;
            uniform vec2 u_sc_light0_extra;
            uniform vec4 u_sc_light1_data;
            uniform vec4 u_sc_light1_color;
            uniform vec2 u_sc_light1_extra;
            uniform vec4 u_sc_light2_data;
            uniform vec4 u_sc_light2_color;
            uniform vec2 u_sc_light2_extra;
            uniform vec4 u_sc_light3_data;
            uniform vec4 u_sc_light3_color;
            uniform vec2 u_sc_light3_extra;
            uniform vec4 u_sc_probe0_data;
            uniform vec3 u_sc_probe0_color;
            uniform vec4 u_sc_probe1_data;
            uniform vec3 u_sc_probe1_color;
            uniform vec4 u_sc_probe2_data;
            uniform vec3 u_sc_probe2_color;
            uniform vec4 u_sc_probe3_data;
            uniform vec3 u_sc_probe3_color;
            uniform vec4 u_sc_probe4_data;
            uniform vec3 u_sc_probe4_color;
            uniform vec4 u_sc_probe5_data;
            uniform vec3 u_sc_probe5_color;
            uniform vec4 u_sc_probe6_data;
            uniform vec3 u_sc_probe6_color;
            uniform vec4 u_sc_probe7_data;
            uniform vec3 u_sc_probe7_color;
            varying vec2 v_sc_screen;
            varying vec2 v_sc_center;
        """,
    "vertex_150": """
            vec2 sc_live_screen = vec2(
                gl_Position.x * 0.5 + 0.5,
                -gl_Position.y * 0.5 + 0.5
            );
            vec4 sc_center_position = u_transform * vec4(
                u_model_size * u_sc_form_center,
                0.0,
                1.0
            );
            vec2 sc_live_center = vec2(
                sc_center_position.x * 0.5 + 0.5,
                -sc_center_position.y * 0.5 + 0.5
            );
            vec2 sc_snapshot_screen = u_sc_snapshot_rect.xy
                + a_tex_coord * u_sc_snapshot_rect.zw;
            vec2 sc_snapshot_center = u_sc_snapshot_rect.xy
                + u_sc_form_center * u_sc_snapshot_rect.zw;
            v_sc_screen = mix(
                sc_live_screen,
                sc_snapshot_screen,
                u_sc_use_snapshot_rect
            );
            v_sc_center = mix(
                sc_live_center,
                sc_snapshot_center,
                u_sc_use_snapshot_rect
            );
            v_sc_center = mix(v_sc_center, u_sc_group_anchor.xy, u_sc_group_anchor.z);
        """,
    "fragment_functions": """
            vec3 scenelight_sprite_light(vec4 light, vec3 color, vec3 normal, float aspect) {
                if (light.w <= 0.0) return vec3(0.0);
                vec2 delta = (light.xy - v_sc_screen) * vec2(aspect, 1.0);
                float distance = length(delta) / max(light.z, 0.001);
                float falloff = 1.0 - smoothstep(0.0, 1.0, distance);
                vec3 direction = normalize(vec3(delta, 0.12));
                float facing = 0.25 + 0.75 * max(dot(normal, direction), 0.0);
                return max(color, vec3(0.0)) * light.w * falloff * falloff * facing;
            }

            vec4 scenelight_sprite_halo(sampler2D source_texture, float lod_bias, vec2 uv_center, vec2 canvas_size, vec2 glow, vec4 tint) {
                vec4 sum = vec4(0.0);
                float weights = 0.0;
                // Isotropic source-pixel radius, independent of canvas aspect.
                vec2 radius = 0.04 * glow.y
                    * min(canvas_size.x, canvas_size.y)
                    / max(canvas_size, vec2(1.0));
                for (int i = 0; i < 64; i++) {
                    float fraction = (float(i) + 0.5) / 64.0;
                    float angle = float(i) * 2.39996323;
                    vec2 uv = uv_center + sqrt(fraction) * radius * vec2(cos(angle), sin(angle));
                    float weight = exp(-4.0 * fraction);
                    // Clamp-to-edge would extrude edge pixels into the halo.
                    if (min(uv.x, uv.y) >= 0.0 && max(uv.x, uv.y) <= 1.0) {
                        sum += texture2D(source_texture, uv, lod_bias) * weight;
                    }
                    weights += weight;
                }
                vec4 blurred = sum / weights;
                float opacity = 1.0 - exp(-blurred.a * glow.x * 1.8);
                vec3 color = clamp(blurred.rgb / max(blurred.a, 0.001) * 1.25, 0.0, 1.0);
                color = mix(color, tint.rgb * max(color.r, max(color.g, color.b)), tint.a);
                return vec4(color * opacity, opacity);
            }
            vec2 scenelight_field_uv(vec2 screen_uv, vec4 tile) {
                vec2 half_texel = u_sc_atlas_texel * 0.5;
                return clamp(tile.xy + screen_uv * tile.zw,
                    tile.xy + half_texel, tile.xy + tile.zw - half_texel);
            }

            vec2 scenelight_atlas_uv(vec2 screen_uv) {
                vec2 half_texel = u_sc_atlas_texel * 0.5;
                vec2 tile_min = u_sc_scene_uv.xy + half_texel;
                vec2 tile_max = u_sc_scene_uv.xy + u_sc_scene_uv.zw - half_texel;
                return clamp(u_sc_scene_uv.xy + screen_uv * u_sc_scene_uv.zw, tile_min, tile_max);
            }

            vec4 scenelight_scene_at(sampler2D source_field, vec2 screen_uv) {
                vec4 current = texture2D(source_field, scenelight_atlas_uv(screen_uv));
                if (u_sc_scene_blend <= 0.0) return current;
                vec4 following = texture2D(source_field,
                    scenelight_field_uv(screen_uv, u_sc_scene_uv_next));
                return mix(current, following, u_sc_scene_blend);
            }

            vec3 scenelight_wrap_at(vec2 screen_uv) {
                vec2 half_texel = u_sc_wrap_texel * 0.5;
                vec2 current_uv = clamp(u_sc_wrap_uv.xy + screen_uv * u_sc_wrap_uv.zw,
                    u_sc_wrap_uv.xy + half_texel, u_sc_wrap_uv.xy + u_sc_wrap_uv.zw - half_texel);
                vec3 current = texture2D(tex6, current_uv).rgb;
                if (u_sc_wrap_blend <= 0.0) return current;
                vec2 next_uv = clamp(u_sc_wrap_uv_next.xy + screen_uv * u_sc_wrap_uv_next.zw,
                    u_sc_wrap_uv_next.xy + half_texel, u_sc_wrap_uv_next.xy + u_sc_wrap_uv_next.zw - half_texel);
                return mix(current, texture2D(tex6, next_uv).rgb, u_sc_wrap_blend);
            }

            vec4 scenelight_transport_at(float plane, vec2 screen_uv) {
                vec2 grid_position = vec2(
                    clamp(screen_uv.x, 0.0, 1.0),
                    clamp(screen_uv.y / max(u_sc_transport_subject_y_max, 0.001), 0.0, 1.0)
                );
                vec2 grid_texel_position = vec2(
                    0.5 + grid_position.x * (u_sc_transport_grid.x - 1.0),
                    0.5 + grid_position.y * (u_sc_transport_grid.y - 1.0)
                );
                vec2 local_uv = grid_texel_position / u_sc_transport_grid;
                vec2 atlas_uv = vec2(
                    u_sc_transport_uv.x + (plane + local_uv.x) * u_sc_transport_uv.z,
                    u_sc_transport_uv.y + local_uv.y * u_sc_transport_uv.w
                );
                // V5 transport planes are deliberately opaque. Independent
                // scalars live in RGB-only planes, preventing Ren'Py's texture
                // premultiplication from quantizing chroma in dark scenes.
                return texture2D(tex7, atlas_uv);
            }

            float scenelight_emitter_at(vec2 screen_uv) {
                return scenelight_scene_at(tex2, screen_uv).a;
            }

            vec3 scenelight_irradiance_at(vec2 screen_uv) {
                return scenelight_scene_at(tex1, screen_uv).rgb;
            }

            float scenelight_straight_luma(vec4 pixel) {
                vec3 straight_rgb = pixel.rgb / max(pixel.a, 0.001);
                vec3 low = straight_rgb / 12.92;
                vec3 high = pow((straight_rgb + vec3(0.055)) / 1.055, vec3(2.4));
                vec3 linear_rgb = mix(low, high, step(vec3(0.04045), straight_rgb));
                return dot(linear_rgb, vec3(0.2126, 0.7152, 0.0722));
            }

            vec3 scenelight_srgb_to_linear(vec3 color) {
                color = max(color, vec3(0.0));
                vec3 low = color / 12.92;
                vec3 high = pow((color + vec3(0.055)) / 1.055, vec3(2.4));
                return mix(low, high, step(vec3(0.04045), color));
            }

            vec3 scenelight_linear_to_srgb(vec3 color) {
                color = max(color, vec3(0.0));
                vec3 low = color * 12.92;
                vec3 high = 1.055 * pow(color, vec3(1.0 / 2.4)) - vec3(0.055);
                return mix(low, high, step(vec3(0.0031308), color));
            }

            vec3 scenelight_unit_energy(vec3 chroma) {
                float energy = dot(chroma, vec3(0.2126, 0.7152, 0.0722));
                return clamp(chroma / max(energy, 0.001), vec3(0.45), vec3(2.4));
            }

            // Adjust incident light colors, never select/repaint artwork pixels.
            // Each independent light contribution passes through this once.
            vec3 scenelight_adjust_light_color(vec3 color, vec4 adjustment, float tolerance) {
                if (abs(adjustment.a) < 0.000001) return color;
                vec3 weights = vec3(0.2126, 0.7152, 0.0722);
                float energy = dot(color, weights);
                vec3 target = scenelight_srgb_to_linear(adjustment.rgb);
                vec3 direction = color - vec3(energy);
                vec3 target_direction = target - vec3(dot(target, weights));
                float magnitude = length(direction);
                float target_magnitude = length(target_direction);
                if (energy < 0.000001 || magnitude < 0.000001 || target_magnitude < 0.000001) return color;
                float distance = sqrt(max(0.0, 0.5 * (1.0 - clamp(
                    dot(direction / magnitude, target_direction / target_magnitude), -1.0, 1.0))));
                float match_color = 1.0 - smoothstep(tolerance, tolerance + 0.10, distance);
                match_color *= smoothstep(0.015, 0.08, magnitude / max(energy, 0.001));
                vec3 adjusted = max(vec3(0.0), vec3(energy)
                    + direction * (1.0 + adjustment.a * match_color));
                return adjusted * (energy / max(dot(adjusted, weights), 0.000001));
            }

            float scenelight_fx_hash(vec2 value) {
                return fract(sin(dot(value, vec2(127.1, 311.7))) * 43758.5453123);
            }

            float scenelight_fx_rain_streak(
                vec2 sprite_uv,
                float time,
                float wind,
                float scale
            ) {
                vec2 rain_uv = sprite_uv;
                rain_uv.x -= rain_uv.y * wind * 0.28;
                rain_uv *= vec2(42.0, 9.0) / max(scale, 0.25);
                vec2 cell = floor(rain_uv);
                vec2 local = fract(rain_uv);
                float random = scenelight_fx_hash(cell);
                float phase = fract(local.y + time * (0.70 + random * 0.85) + random);
                float trail_x = abs(local.x - (0.14 + random * 0.72));
                float thin = 1.0 - smoothstep(0.012, 0.055, trail_x);
                float head = 1.0 - smoothstep(0.02, 0.16, phase);
                float tail = smoothstep(0.04, 0.22, phase) * (1.0 - smoothstep(0.22, 0.92, phase));
                return thin * (head + tail * 0.42) * step(0.40, random);
            }

            float scenelight_height(vec2 sprite_uv, sampler2D source_texture, float lod_bias) {
                if (u_sc_has_form > 0.5) {
                    float encoded = texture2D(
                        tex4,
                        clamp(sprite_uv, vec2(0.0), vec2(1.0))
                    ).r;
                    return mix(u_sc_height_range.x, u_sc_height_range.y, encoded);
                }
                vec4 pixel = texture2D(
                    source_texture,
                    clamp(sprite_uv, vec2(0.0), vec2(1.0)),
                    lod_bias
                );
                return pixel.a * 0.72 + scenelight_straight_luma(pixel) * 0.28;
            }

            vec3 scenelight_form_normal(
                vec2 sprite_uv,
                vec2 sprite_texel,
                sampler2D source_texture,
                float lod_bias
            ) {
                if (u_sc_has_form > 0.5) {
                    vec2 encoded = texture2D(tex3, clamp(sprite_uv, vec2(0.0), vec2(1.0))).rg;
                    vec2 normal_xy = encoded * 2.0 - 1.0;
                    float normal_z = sqrt(max(1.0 - dot(normal_xy, normal_xy), 0.0001));
                    return normalize(vec3(normal_xy, normal_z));
                }
                float height_left = scenelight_height(
                    sprite_uv - vec2(sprite_texel.x * 2.0, 0.0), source_texture, lod_bias
                );
                float height_right = scenelight_height(
                    sprite_uv + vec2(sprite_texel.x * 2.0, 0.0), source_texture, lod_bias
                );
                float height_up = scenelight_height(
                    sprite_uv - vec2(0.0, sprite_texel.y * 2.0), source_texture, lod_bias
                );
                float height_down = scenelight_height(
                    sprite_uv + vec2(0.0, sprite_texel.y * 2.0), source_texture, lod_bias
                );
                return normalize(vec3(
                    (height_left - height_right) * 2.8,
                    (height_up - height_down) * 2.8,
                    1.0
                ));
            }

            vec4 scenelight_light_vector_weight(
                vec4 data,
                vec4 color,
                vec2 extra,
                float secondary_scale,
                vec2 fallback_direction
            ) {
                float enabled = extra.y;
                float screen_distance = distance(data.xy, v_sc_center);
                float effective_distance = max(screen_distance - data.z * 0.35, 0.0);
                float positional_falloff = clamp(
                    1.15 / (1.0 + 1.8 * effective_distance * effective_distance),
                    0.55,
                    1.15
                );
                float weight = data.w * secondary_scale
                    * (0.32 + 0.68 * color.a)
                    * positional_falloff
                    * enabled;
                float elevation = 0.18 + data.z * 0.90;
                vec2 center_delta = data.xy - v_sc_center;
                float center_distance = length(center_delta);
                vec2 center_direction = center_delta / max(center_distance, 0.12);
                center_direction += fallback_direction * step(center_distance, 0.0001) * 0.0001;
                vec3 broad_vector = normalize(vec3(center_direction, elevation));
                vec2 pixel_delta = data.xy - v_sc_screen;
                vec2 pixel_direction = pixel_delta / max(length(pixel_delta), 0.12);
                vec3 point_vector = normalize(vec3(pixel_direction, elevation));
                float emitter_blend = clamp(extra.x, 0.0, 1.0);
                vec3 light_vector = normalize(mix(broad_vector, point_vector, emitter_blend));

                float source_reach = 0.08 + data.z * 0.90;
                float pixel_distance = distance(data.xy, v_sc_screen);
                float falloff = 1.0 / (1.0 + pow(pixel_distance / source_reach, 2.0));
                float center_falloff = 1.0 / (1.0 + pow(screen_distance / source_reach, 2.0));
                float relative_falloff = clamp(falloff / max(center_falloff, 0.0001), 0.32, 1.85);
                float spatial_weight = 1.0 + (relative_falloff - 1.0) * emitter_blend * 0.72;
                return vec4(light_vector, weight * spatial_weight);
            }

            float scenelight_light_base_weight(
                vec4 data,
                vec4 color,
                vec2 extra,
                float secondary_scale
            ) {
                float screen_distance = distance(data.xy, v_sc_center);
                float effective_distance = max(screen_distance - data.z * 0.35, 0.0);
                float positional_falloff = clamp(
                    1.15 / (1.0 + 1.8 * effective_distance * effective_distance),
                    0.55,
                    1.15
                );
                return data.w * secondary_scale
                    * (0.32 + 0.68 * color.a)
                    * positional_falloff
                    * extra.y;
            }

            float scenelight_creative_light_weight(
                vec4 data,
                vec4 color,
                vec2 extra,
                float secondary_scale
            ) {
                float screen_distance = distance(data.xy, v_sc_center);
                float effective_distance = max(screen_distance - data.z * 0.35, 0.0);
                float positional_falloff = clamp(
                    1.15 / (1.0 + 1.8 * effective_distance * effective_distance),
                    0.55,
                    1.15
                );
                float source_present = smoothstep(0.0, 0.65, data.w + extra.x);
                float source_reach = 0.08 + data.z * 0.90;
                float pixel_distance = distance(data.xy, v_sc_screen);
                float falloff = 1.0 / (1.0 + pow(pixel_distance / source_reach, 2.0));
                float center_falloff = 1.0 / (1.0 + pow(screen_distance / source_reach, 2.0));
                float relative_falloff = clamp(
                    falloff / max(center_falloff, 0.0001),
                    0.28,
                    2.10
                );
                return source_present * secondary_scale
                    * (0.32 + 0.68 * color.a)
                    * positional_falloff
                    * relative_falloff
                    * step(0.001, color.a);
            }

            float scenelight_colored_source_support(
                vec4 primary_data,
                vec4 primary_color,
                vec2 primary_extra,
                vec4 source_data,
                vec4 source_color
            ) {
                // A broad hue family is ambient evidence unless a measured
                // emitter agrees with both its color and its location. A
                // white lamp cannot validate unrelated green scenery.
                float compactness = 1.0 - smoothstep(0.55, 0.70, source_data.z);
                float color_agreement = 1.0 - smoothstep(
                    0.18, 0.50,
                    distance(
                        primary_color.rgb / max(length(primary_color.rgb), 0.0001),
                        source_color.rgb / max(length(source_color.rgb), 0.0001)
                    )
                );
                float position_agreement = 1.0 - smoothstep(
                    0.12, 0.32, distance(primary_data.xy, source_data.xy)
                );
                float primary_chroma = max(primary_color.r, max(primary_color.g, primary_color.b))
                    - min(primary_color.r, min(primary_color.g, primary_color.b));
                float emitter = smoothstep(0.12, 0.45, primary_extra.x)
                    * smoothstep(0.15, 0.45, primary_chroma)
                    * color_agreement * position_agreement;
                // Legacy records may contain additional physical lights.
                // They already have measured energy; only hue-only regions
                // (whose physical intensity is zero) need this extra gate.
                return max(step(0.001, source_data.w), max(compactness, emitter));
            }

            float scenelight_separation_pair_evidence(
                vec4 data_a,
                vec4 color_a,
                vec2 extra_a,
                vec4 data_b,
                vec4 color_b,
                vec2 extra_b,
                float layout_mix,
                float support_a,
                float support_b
            ) {
                // Hue-family sources are encoded with physical intensity off
                // (data.w == 0) and their measured source energy in extra.x.
                // Requiring two such sources prevents colorful props or one
                // dominant lamp from turning an ordinary scene into a grade.
                float creative_a = (layout_mix < 0.0 ? 1.0 - step(0.001, data_a.w) : layout_mix)
                    * step(0.001, extra_a.x) * step(0.001, color_a.a);
                float creative_b = (layout_mix < 0.0 ? 1.0 - step(0.001, data_b.w) : layout_mix)
                    * step(0.001, extra_b.x) * step(0.001, color_b.a);
                float chroma_evidence = smoothstep(
                    0.55,
                    0.95,
                    length(color_a.rgb - color_b.rgb)
                );
                float spatial_evidence = smoothstep(
                    0.04,
                    0.24,
                    distance(data_a.xy, data_b.xy)
                );
                float energy_evidence = smoothstep(
                    0.0,
                    0.85,
                    min(extra_a.x, extra_b.x)
                );
                float confidence_evidence = smoothstep(
                    0.0,
                    0.82,
                    min(color_a.a, color_b.a)
                );
                return support_a * support_b * creative_a * creative_b * chroma_evidence
                    * spatial_evidence * energy_evidence * confidence_evidence;
            }

            float scenelight_primary_creative_evidence(
                vec4 primary_data,
                vec4 primary_color,
                vec4 creative_data,
                vec4 creative_color,
                vec2 creative_extra,
                float layout_mix,
                float source_support
            ) {
                // One strongly colored practical plus a neutral key is already
                // a separated-light scene. Keep the gate conservative so a
                // weak saturated prop cannot turn an ordinary photograph into
                // a global grade.
                float primary_present = step(0.001, primary_data.w)
                    * step(0.001, primary_color.a);
                float creative_present = (layout_mix < 0.0 ? 1.0 - step(0.001, creative_data.w) : layout_mix)
                    * step(0.001, creative_extra.x)
                    * step(0.001, creative_color.a);
                float neutral_evidence = 1.0 - smoothstep(
                    0.22,
                    0.40,
                    length(primary_color.rgb - vec3(1.0))
                );
                float chroma_evidence = smoothstep(
                    0.45,
                    0.80,
                    length(primary_color.rgb - creative_color.rgb)
                );
                float spatial_evidence = smoothstep(
                    0.10,
                    0.24,
                    distance(primary_data.xy, creative_data.xy)
                );
                float energy_evidence = smoothstep(0.72, 0.90, creative_extra.x);
                float confidence_evidence = smoothstep(0.72, 0.90, creative_color.a);
                return source_support * primary_present * creative_present * neutral_evidence
                    * chroma_evidence * spatial_evidence
                    * energy_evidence * confidence_evidence;
            }

            vec3 scenelight_center_light_vector(
                vec4 data,
                vec2 fallback_direction
            ) {
                vec2 delta = data.xy - v_sc_center;
                float distance_to_light = length(delta);
                vec2 direction = delta / max(distance_to_light, 0.12);
                direction += fallback_direction * step(distance_to_light, 0.0001) * 0.0001;
                return normalize(vec3(direction, 0.18 + data.z * 0.90));
            }

            float scenelight_filtered_lambert(
                vec3 light_vector,
                vec3 normal0,
                vec3 normal1,
                vec3 normal2,
                vec3 normal3,
                vec3 normal4
            ) {
                // The installed form normal is already spatially filtered.
                // A center-plus-cross kernel preserves the broad Lambert lobe
                // without paying for four redundant diagonal texture reads.
                float value = max(dot(normal0, light_vector), 0.0) * 0.36;
                value += max(dot(normal1, light_vector), 0.0) * 0.16;
                value += max(dot(normal2, light_vector), 0.0) * 0.16;
                value += max(dot(normal3, light_vector), 0.0) * 0.16;
                value += max(dot(normal4, light_vector), 0.0) * 0.16;
                return value;
            }

            float scenelight_ray_shadow(
                vec2 light_direction,
                float elevation,
                vec2 sprite_texel,
                float alpha,
                vec2 sprite_uv,
                vec2 source_resolution,
                sampler2D source_texture,
                float lod_bias
            ) {
                // Self-occlusion needs a prepared height field. Painted RGB
                // is useful for a local normal fallback, but treating eyes or
                // clothing colors as distant blockers projects copies of them
                // across the sprite. Missing maps still receive normal-based
                // directional lighting, rim, bounce, and the other effects.
                if (u_sc_has_form < 0.5) return 0.0;
                float center_height = scenelight_height(
                    sprite_uv, source_texture, lod_bias
                ) + u_sc_height_range.x * 0.0;
                float shadow = 0.0;
                // Six evenly spaced taps retain the full shadow reach. The
                // old fourteen-tap search oversampled a deliberately smooth
                // generated height field and dominated older integrated GPUs.
                for (int ray_step = 1; ray_step <= 6; ray_step++) {
                    float fraction = float(ray_step) / 6.0;
                    float step_distance = min(source_resolution.x, source_resolution.y) * 0.46 * fraction;
                    vec2 ray_uv = sprite_uv + light_direction * sprite_texel * step_distance;
                    float sampled_alpha = texture2D(
                        source_texture, clamp(ray_uv, vec2(0.0), vec2(1.0)), lod_bias
                    ).a;
                    float ray_rise = fraction * (0.22 + 0.34 * elevation);
                    float blocker = max(
                        scenelight_height(ray_uv, source_texture, lod_bias) - center_height - ray_rise,
                        0.0
                    ) * sampled_alpha;
                    shadow = max(shadow, blocker);
                }
                return clamp(shadow * 4.4, 0.0, 1.0) * step(0.001, alpha);
            }

            void scenelight_accumulate_probe(
                vec4 data,
                vec3 color,
                vec3 normal,
                float local_reference,
                inout vec3 probe_rgb,
                inout float probe_weight,
                inout vec3 ground_rgb,
                inout float ground_energy
            ) {
                float incidence = clamp(
                    normal.x * data.x + normal.y * data.y + normal.z * 0.42,
                    0.0,
                    1.0
                );
                float relative_energy = clamp(
                    (data.z + 0.015) / local_reference,
                    0.18,
                    2.6
                );
                float weight = incidence * (0.25 + 0.75 * relative_energy) * data.w;
                probe_rgb += weight * clamp(color, vec3(0.55), vec3(2.1));
                probe_weight += weight;
                float is_ground = step(0.5, data.y) * data.w;
                float energy = (data.z + 0.02) * is_ground;
                ground_rgb += color * energy;
                ground_energy += energy;
            }
        """,
    "fragment_350": """
            // Ren'Py 7 discovers declarations by scanning numbered shader
            // blocks, but not fragment_functions. Keep function-only names
            // visible to that parser without adding GPU work:
            // tex1 tex2 tex3 tex4 tex5 tex6 tex7
            // u_sc_scene_uv u_sc_atlas_texel u_sc_reference_mid
            // u_sc_authored_grade
            // u_sc_chroma_range u_sc_target_range u_sc_shadow_chroma
            // u_sc_local_saturation u_sc_local_contrast u_sc_light_confidence
            // u_sc_source_size u_sc_grain u_sc_sharpness u_sc_has_form
            // u_sc_form_center u_sc_mean_form_visibility u_sc_form_contrast_mid
            // u_sc_height_range u_sc_noise_range u_sc_local_luminance
            // u_sc_has_transport u_sc_live_background u_sc_transport_uv
            // u_sc_transport_grid u_sc_transport_subject_y_max
            // u_sc_light0_data u_sc_light0_color u_sc_light0_extra
            // u_sc_light1_data u_sc_light1_color u_sc_light1_extra
            // u_sc_light2_data u_sc_light2_color u_sc_light2_extra
            // u_sc_light3_data u_sc_light3_color u_sc_light3_extra
            // u_sc_probe0_data u_sc_probe0_color u_sc_probe1_data u_sc_probe1_color
            // u_sc_probe2_data u_sc_probe2_color u_sc_probe3_data u_sc_probe3_color
            // u_sc_probe4_data u_sc_probe4_color u_sc_probe5_data u_sc_probe5_color
            // u_sc_probe6_data u_sc_probe6_color u_sc_probe7_data u_sc_probe7_color
            // Compose from the fragment color produced by any lower-priority
            // shader part instead of resampling tex0. Most foreign mesh
            // transforms are isolated passes, but this also preserves a
            // deliberately combined Ren'Py shader stack.
            vec4 source = gl_FragColor;
            float sc_live_grain = u_sc_grain;
            float sc_live_sharpness = u_sc_sharpness;
            if (u_sc_live_analysis > 0.5) {
                vec3 sc_live_grain_rgb = texture2D(tex7, vec2(0.5 / 416.0, 9.5 / 10.0)).rgb;
                vec3 sc_live_sharpness_rgb = texture2D(tex7, vec2(1.5 / 416.0, 9.5 / 10.0)).rgb;
                vec3 sc_live_decode = vec3(65536.0, 256.0, 1.0) * (255.0 / 16777215.0);
                sc_live_grain = dot(sc_live_grain_rgb, sc_live_decode);
                sc_live_sharpness = dot(sc_live_sharpness_rgb, sc_live_decode);
            }
            float sc_glitch_intensity = u_sc_glitch_data.x;
            if (sc_glitch_intensity > 0.0001) {
                float sc_glitch_tick = floor(
                    u_sc_effect_time * max(u_sc_glitch_data.w, 0.05) * 18.0
                );
                float sc_glitch_rows = max(18.0, 84.0 / max(u_sc_glitch_data.z, 0.25));
                float sc_glitch_row = floor(v_tex_coord.y * sc_glitch_rows);
                float sc_glitch_random = scenelight_fx_hash(
                    vec2(sc_glitch_row + u_sc_glitch_extra.w, sc_glitch_tick)
                );
                float sc_glitch_gate = step(0.78 - 0.48 * sc_glitch_intensity, sc_glitch_random);
                float sc_glitch_offset = (
                    sc_glitch_random - 0.5
                ) * 0.075 * u_sc_glitch_extra.x * sc_glitch_intensity * sc_glitch_gate;
                vec2 sc_glitch_uv = clamp(
                    v_tex_coord + vec2(sc_glitch_offset, 0.0),
                    vec2(0.0),
                    vec2(1.0)
                );
                source = texture2D(tex0, sc_glitch_uv, u_lod_bias);
                float sc_split = 0.010 * u_sc_glitch_data.y * sc_glitch_intensity;
                vec4 sc_red = texture2D(
                    tex0,
                    clamp(sc_glitch_uv + vec2(sc_split, 0.0), vec2(0.0), vec2(1.0)),
                    u_lod_bias
                );
                vec4 sc_blue = texture2D(
                    tex0,
                    clamp(sc_glitch_uv - vec2(sc_split, 0.0), vec2(0.0), vec2(1.0)),
                    u_lod_bias
                );
                source.r = sc_red.r;
                source.b = sc_blue.b;
            }
            float alpha = source.a;
            vec3 base_srgb = source.rgb / max(alpha, 0.001);
            vec3 base = scenelight_srgb_to_linear(base_srgb);
            float base_luma = dot(base, vec3(0.2126, 0.7152, 0.0722));
            float material_response = smoothstep(0.012, 0.115, base_luma);
            float sc_height_dependency = u_sc_height_range.x * 0.0;
            // Ren'Py discovers varyings from the fragment body rather than
            // recursively through helper functions. Keep this explicit zero
            // dependency so v_sc_screen remains available to the light and
            // shadow transport helpers above.
            vec2 sc_screen_dependency = v_sc_screen * 0.0;
            vec4 sc_transport_dependency = texture2D(tex7, vec2(0.0)) * 0.0;
            sc_transport_dependency += vec4(
                u_sc_transport_uv.xy,
                u_sc_transport_grid.x / max(u_sc_transport_grid.y, 1.0),
                u_sc_transport_subject_y_max
            ) * 0.0;

            // The CPU reference meters one local environment around the
            // subject. Sampling ambient color independently behind every body
            // pixel made the former runtime look like a translucent cutout of
            // the background. Keep broad adaptation constant across the form;
            // only explicit lights and edge wrap are spatially local.
            vec2 scene_uv = scenelight_atlas_uv(v_sc_center);
            vec4 irradiance_sample = scenelight_scene_at(tex1, v_sc_center);
            vec4 emitter_sample = scenelight_scene_at(tex2, v_sc_center);
            vec4 transport_scalar = scenelight_transport_at(0.0, v_sc_center);
            vec4 transport_ambient = scenelight_transport_at(1.0, v_sc_center);
            vec4 transport_global_extra = scenelight_transport_at(2.0, v_sc_center);
            float transport_mix = step(0.5, u_sc_has_transport);
            // A marker distinguishes continuous slots from installed legacy
            // fields without adding textures or vertex outputs.
            float sc_layout_mix = transport_mix > 0.5 && transport_global_extra.b > 0.5
                ? transport_global_extra.g : -1.0;
            vec3 ambient_chroma = mix(
                scenelight_unit_energy(irradiance_sample.rgb * u_sc_chroma_range),
                transport_ambient.rgb * u_sc_chroma_range,
                transport_mix
            );
            vec3 emitter_chroma = scenelight_unit_energy(emitter_sample.rgb * u_sc_chroma_range);
            float local_contrast = mix(u_sc_local_contrast, transport_scalar.r * 2.0, transport_mix);
            float local_saturation = mix(u_sc_local_saturation, transport_scalar.g, transport_mix);
            float local_luminance = mix(u_sc_local_luminance, transport_scalar.b, transport_mix);
            // New fields encode sqrt(exposure) to retain dark-scene precision.
            // Older installed fields retain their original linear decoding.
            float target_sample = transport_global_extra.r;
            if (transport_global_extra.b > 0.5 && transport_global_extra.b < 0.9) {
                target_sample *= target_sample;
            }
            float transported_target_mid = mix(
                irradiance_sample.a * u_sc_target_range,
                target_sample * u_sc_target_range,
                transport_mix
            );
            // Only the legacy static-field fallback needs local frame metering.
            // Live and prepared fields already describe this exact video frame.
            if (u_sc_live_background > 0.5 && u_sc_live_analysis < 0.5) {
                vec3 live_environment = scenelight_srgb_to_linear(
                    scenelight_wrap_at(v_sc_center)
                );
                float live_luminance = dot(
                    live_environment,
                    vec3(0.2126, 0.7152, 0.0722)
                );
                float live_exposure_ratio = sqrt(
                    (live_luminance + 0.008) / (local_luminance + 0.008)
                );
                ambient_chroma = scenelight_unit_energy(live_environment);
                transported_target_mid = clamp(
                    transported_target_mid * live_exposure_ratio,
                    0.035,
                    u_sc_target_range
                );
                local_luminance = live_luminance;
            }
            vec3 shadow_chroma = mix(
                u_sc_shadow_chroma,
                scenelight_unit_energy(ambient_chroma * vec3(0.91, 0.96, 1.07)),
                transport_mix
            );

            // Offset in screen space, then clamp inside the current atlas tile.
            // Offsetting the atlas UV itself can leak light from a neighboring
            // background when a character reaches a screen edge.
            vec2 screen_dx = vec2(u_sc_atlas_texel.x / u_sc_scene_uv.z * 1.5, 0.0);
            vec2 screen_dy = vec2(0.0, u_sc_atlas_texel.y / u_sc_scene_uv.w * 1.5);
            float field_left = scenelight_emitter_at(v_sc_center - screen_dx);
            float field_right = scenelight_emitter_at(v_sc_center + screen_dx);
            float field_up = scenelight_emitter_at(v_sc_center - screen_dy);
            float field_down = scenelight_emitter_at(v_sc_center + screen_dy);
            vec2 light_gradient = vec2(field_right - field_left, field_down - field_up);
            light_gradient += vec2(0.0, -0.012);
            vec2 light_direction = normalize(light_gradient + vec2(0.00001, -0.00001));

            // Lighting does not invent geometry on the transparent canvas.
            if (alpha > 0.001) {
            vec2 sprite_texel = 1.0 / max(u_sc_sprite_size, vec2(1.0));
            vec3 normal = scenelight_form_normal(v_tex_coord, sprite_texel, tex0, u_lod_bias);
            // Fetch the Gaussian form neighborhood once and reuse it for all
            // four lights. This is both exact to the chosen kernel and much
            // cheaper than resampling the normal map inside every light lobe.
            vec2 form_filter_offset = sprite_texel * 1.310548;
            vec3 normal1 = scenelight_form_normal(v_tex_coord + vec2(form_filter_offset.x, 0.0), sprite_texel, tex0, u_lod_bias);
            vec3 normal2 = scenelight_form_normal(v_tex_coord - vec2(form_filter_offset.x, 0.0), sprite_texel, tex0, u_lod_bias);
            vec3 normal3 = scenelight_form_normal(v_tex_coord + vec2(0.0, form_filter_offset.y), sprite_texel, tex0, u_lod_bias);
            vec3 normal4 = scenelight_form_normal(v_tex_coord - vec2(0.0, form_filter_offset.y), sprite_texel, tex0, u_lod_bias);
            vec4 transport_light0_position = scenelight_transport_at(3.0, v_sc_center);
            vec4 transport_light0_color_sample = scenelight_transport_at(4.0, v_sc_center);
            vec4 transport_light0_scalar = scenelight_transport_at(5.0, v_sc_center);
            vec4 transport_light1_position = scenelight_transport_at(6.0, v_sc_center);
            vec4 transport_light1_color_sample = scenelight_transport_at(7.0, v_sc_center);
            vec4 transport_light1_scalar = scenelight_transport_at(8.0, v_sc_center);
            vec4 transport_light2_position = scenelight_transport_at(9.0, v_sc_center);
            vec4 transport_light2_color_sample = scenelight_transport_at(10.0, v_sc_center);
            vec4 transport_light2_scalar = scenelight_transport_at(11.0, v_sc_center);
            vec4 transport_light3_position = scenelight_transport_at(12.0, v_sc_center);
            vec4 transport_light3_color_sample = scenelight_transport_at(13.0, v_sc_center);
            vec4 transport_light3_scalar = scenelight_transport_at(14.0, v_sc_center);
            vec4 sc_light0_data = mix(
                u_sc_light0_data,
                vec4(transport_light0_position.rgb, transport_light0_scalar.r),
                transport_mix
            );
            vec4 sc_light1_data = mix(
                u_sc_light1_data,
                vec4(transport_light1_position.rgb, transport_light1_scalar.r),
                transport_mix
            );
            vec4 sc_light2_data = mix(
                u_sc_light2_data,
                vec4(transport_light2_position.rgb, transport_light2_scalar.r),
                transport_mix
            );
            vec4 sc_light3_data = mix(
                u_sc_light3_data,
                vec4(transport_light3_position.rgb, transport_light3_scalar.r),
                transport_mix
            );
            vec4 sc_light0_color = mix(
                u_sc_light0_color,
                vec4(transport_light0_color_sample.rgb * u_sc_chroma_range, transport_light0_scalar.g),
                transport_mix
            );
            vec4 sc_light1_color = mix(
                u_sc_light1_color,
                vec4(transport_light1_color_sample.rgb * u_sc_chroma_range, transport_light1_scalar.g),
                transport_mix
            );
            vec4 sc_light2_color = mix(
                u_sc_light2_color,
                vec4(transport_light2_color_sample.rgb * u_sc_chroma_range, transport_light2_scalar.g),
                transport_mix
            );
            vec4 sc_light3_color = mix(
                u_sc_light3_color,
                vec4(transport_light3_color_sample.rgb * u_sc_chroma_range, transport_light3_scalar.g),
                transport_mix
            );
            vec2 sc_light0_extra = mix(
                u_sc_light0_extra,
                vec2(transport_light0_scalar.b, step(0.001, transport_light0_scalar.r)),
                transport_mix
            );
            vec2 sc_light1_extra = mix(
                u_sc_light1_extra,
                vec2(transport_light1_scalar.b, step(0.001, transport_light1_scalar.r)),
                transport_mix
            );
            vec2 sc_light2_extra = mix(
                u_sc_light2_extra,
                vec2(transport_light2_scalar.b, step(0.001, transport_light2_scalar.r)),
                transport_mix
            );
            vec2 sc_light3_extra = mix(
                u_sc_light3_extra,
                vec2(transport_light3_scalar.b, step(0.001, transport_light3_scalar.r)),
                transport_mix
            );
            vec4 light0 = scenelight_light_vector_weight(
                sc_light0_data, sc_light0_color, sc_light0_extra, 1.0, light_direction
            );
            vec4 light1 = scenelight_light_vector_weight(
                sc_light1_data, sc_light1_color, sc_light1_extra, 0.82, light_direction
            );
            vec4 light2 = scenelight_light_vector_weight(
                sc_light2_data, sc_light2_color, sc_light2_extra, 0.82, light_direction
            );
            vec4 light3 = scenelight_light_vector_weight(
                sc_light3_data, sc_light3_color, sc_light3_extra, 0.82, light_direction
            );
            // CPU parity: spatial falloff belongs only in the transported
            // numerator. Dividing by a spatially varying denominator cancels
            // the local bright/dark response and reduces the result to a
            // scene-colored wash.
            float base_light_weight0 = scenelight_light_base_weight(
                sc_light0_data, sc_light0_color, sc_light0_extra, 1.0
            );
            float base_light_weight1 = scenelight_light_base_weight(
                sc_light1_data, sc_light1_color, sc_light1_extra, 0.82
            );
            float base_light_weight2 = scenelight_light_base_weight(
                sc_light2_data, sc_light2_color, sc_light2_extra, 0.82
            );
            float base_light_weight3 = scenelight_light_base_weight(
                sc_light3_data, sc_light3_color, sc_light3_extra, 0.82
            );
            float total_light_weight = max(
                base_light_weight0 + base_light_weight1 + base_light_weight2 + base_light_weight3,
                0.0001
            );
            vec3 center_light_vector0 = scenelight_center_light_vector(sc_light0_data, light_direction);
            vec3 center_light_vector1 = scenelight_center_light_vector(sc_light1_data, light_direction);
            vec3 center_light_vector2 = scenelight_center_light_vector(sc_light2_data, light_direction);
            vec3 center_light_vector3 = scenelight_center_light_vector(sc_light3_data, light_direction);
            vec2 primary_ray_direction = normalize(sc_light0_data.xy - v_sc_center + vec2(0.00001));
            float primary_ray_elevation = normalize(vec3(
                primary_ray_direction,
                0.18 + sc_light0_data.z * 0.90
            )).z;
            float ray_shadow = 0.0;
            if (sc_light0_extra.y > 0.5 && u_sc_calibration2.x > 0.0001) {
                ray_shadow = scenelight_ray_shadow(
                    primary_ray_direction,
                    primary_ray_elevation,
                    sprite_texel,
                    alpha,
                    v_tex_coord,
                    u_sc_sprite_size,
                    tex0,
                    u_lod_bias
                );
            }
            vec2 secondary_ray_direction = normalize(sc_light1_data.xy - v_sc_center + vec2(0.00001));
            float secondary_ray_elevation = normalize(vec3(
                secondary_ray_direction,
                0.18 + sc_light1_data.z * 0.90
            )).z;
            float secondary_ray_shadow = 0.0;
            if (sc_light1_extra.y > 0.5 && u_sc_calibration2.x > 0.0001) {
                secondary_ray_shadow = scenelight_ray_shadow(
                    secondary_ray_direction,
                    secondary_ray_elevation,
                    sprite_texel,
                    alpha,
                    v_tex_coord,
                    u_sc_sprite_size,
                    tex0,
                    u_lod_bias
                );
            }

            float lambert0 = scenelight_filtered_lambert(light0.xyz, normal, normal1, normal2, normal3, normal4) * (1.0 - ray_shadow * 0.58);
            float lambert1 = scenelight_filtered_lambert(light1.xyz, normal, normal1, normal2, normal3, normal4) * (1.0 - secondary_ray_shadow * 0.58);
            float lambert2 = scenelight_filtered_lambert(light2.xyz, normal, normal1, normal2, normal3, normal4);
            float lambert3 = scenelight_filtered_lambert(light3.xyz, normal, normal1, normal2, normal3, normal4);
            float lambert = clamp(
                (lambert0 * light0.w + lambert1 * light1.w + lambert2 * light2.w + lambert3 * light3.w)
                    / total_light_weight,
                0.0,
                1.0
            );
            // A generated pseudo-normal cannot distinguish real relief from
            // a flat painted boundary between expression/hair layers. Use
            // nearby source structure as receiver confidence before that
            // normal can drive a narrow specular response. Diffuse form stays
            // on its established path; the gate only prevents false glossy
            // bands across smooth paint. Sprites without exact form maps remain
            // unchanged as well.
            float form_detail_left = scenelight_straight_luma(texture2D(
                tex0,
                clamp(v_tex_coord - vec2(sprite_texel.x * 2.0, 0.0), vec2(0.0), vec2(1.0)),
                u_lod_bias
            ));
            float form_detail_right = scenelight_straight_luma(texture2D(
                tex0,
                clamp(v_tex_coord + vec2(sprite_texel.x * 2.0, 0.0), vec2(0.0), vec2(1.0)),
                u_lod_bias
            ));
            float form_detail_up = scenelight_straight_luma(texture2D(
                tex0,
                clamp(v_tex_coord - vec2(0.0, sprite_texel.y * 2.0), vec2(0.0), vec2(1.0)),
                u_lod_bias
            ));
            float form_detail_down = scenelight_straight_luma(texture2D(
                tex0,
                clamp(v_tex_coord + vec2(0.0, sprite_texel.y * 2.0), vec2(0.0), vec2(1.0)),
                u_lod_bias
            ));
            float form_detail_span = abs(form_detail_left - form_detail_right)
                + abs(form_detail_up - form_detail_down);
            float form_detail_visibility = mix(
                1.0,
                smoothstep(0.018, 0.110, form_detail_span),
                step(0.5, u_sc_has_form)
            );
            vec3 source_color_field = (
                lambert0 * light0.w * sc_light0_color.rgb
                + lambert1 * light1.w * sc_light1_color.rgb
                + lambert2 * light2.w * sc_light2_color.rgb
                + lambert3 * light3.w * sc_light3_color.rgb
            ) / total_light_weight;
            float sc_creative_weight0 = scenelight_creative_light_weight(
                sc_light0_data, sc_light0_color, sc_light0_extra, 1.0
            );
            float sc_creative_weight1 = scenelight_creative_light_weight(
                sc_light1_data, sc_light1_color, sc_light1_extra, 1.0
            );
            float sc_creative_weight2 = scenelight_creative_light_weight(
                sc_light2_data, sc_light2_color, sc_light2_extra, 1.0
            );
            float sc_creative_weight3 = scenelight_creative_light_weight(
                sc_light3_data, sc_light3_color, sc_light3_extra, 1.0
            );
            vec3 primary_light_vector = light0.xyz;

            vec4 form_aux = texture2D(tex4, clamp(v_tex_coord, vec2(0.0), vec2(1.0)));
            float surface_ao = mix(0.0, form_aux.g, step(0.5, u_sc_has_form));
            float target_mid = transported_target_mid
                + sc_height_dependency
                + dot(sc_screen_dependency, vec2(1.0))
                + dot(sc_transport_dependency, vec4(1.0));
            float scene_exposure = clamp(target_mid / u_sc_reference_mid, 0.0001, 2.15);
            // Source art is already exposed. Bright walls/sky should not nearly
            // double it. Preserve dark-scene gain and the slope at unity; only
            // automatic positive gain has a shoulder. Authored bias stays free.
            float sc_exposure_boost = max(scene_exposure - 1.0, 0.0);
            scene_exposure = min(scene_exposure, 1.0)
                + sc_exposure_boost / (1.0 + 4.0 * sc_exposure_boost);
            float auto_amount = u_sc_calibration0.x * u_sc_strength;
            // A Ren'Py matrixcolor outside this displayable is authored final
            // grading, not unlit material. Keep generated form and direction,
            // but do not meter the same scene exposure through that grade a
            // second time. Ordinary sprites remain bit-for-bit on the original
            // path because their authored-grade value is zero.
            float sc_authored_grade = clamp(u_sc_authored_grade, 0.0, 1.0)
                * step(0.0001, u_sc_strength);
            float sc_environment_adaptation = 1.0 - sc_authored_grade;
            // Incoming paint may already be exposed by a whole-image alias.
            // New highlights and the contrast pivot still need the absolute
            // exposure, including exposure inherited through authored grading.
            float input_exposure = pow(scene_exposure, auto_amount * sc_environment_adaptation * u_sc_exposure_owner)
                * exp2(u_sc_calibration0.y * u_sc_strength * u_sc_exposure_bias_owner);
            float exposure = pow(scene_exposure, u_sc_exposure_auto)
                * exp2(u_sc_exposure_bias);
            float confidence = 0.34 + 0.66 * mix(u_sc_light_confidence, sc_light0_color.a, transport_mix);
            float key_amount = u_sc_calibration1.w * confidence * u_sc_strength;
            // High-key broad illumination in a photograph has normally
            // already undergone camera white balance. Classify that condition
            // from scene transport only; character identity, palette, skin,
            // filenames, and background names never enter the gate.
            float sc_broad_radius = mix(u_sc_source_size, sc_light0_data.z, transport_mix);
            float sc_primary_confidence = mix(
                u_sc_light_confidence, sc_light0_color.a, transport_mix
            );
            float sc_primary_emission = mix(0.0, sc_light0_extra.x, transport_mix);
            float sc_high_key = smoothstep(0.30, 0.46, local_luminance);
            float sc_broad = smoothstep(0.62, 0.90, sc_broad_radius);
            float sc_uncertain = 1.0 - smoothstep(0.34, 0.60, sc_primary_confidence);
            float sc_diffuse = 1.0 - smoothstep(0.12, 0.35, sc_primary_emission);
            float sc_chroma_guard = clamp(
                sc_high_key * sc_broad * sc_uncertain * sc_diffuse,
                0.0,
                1.0
            );

            // Match the standalone renderer's energy-balanced form model.
            // Near-black fur, line art, and cloth retain a deliberately
            // shallower generated response. Normalize around the expected
            // broad-surface response so a complex silhouette cannot become
            // globally brighter merely because it has more reconstructed
            // normals facing the light.
            // Share diffuse energy between ambient fill and directional light.
            // The previous large constant floor overwhelmed normal incidence.
            float diffuse_fill = 0.22;
            float diffuse_span = 0.22 + key_amount * 1.35;
            float form_light = diffuse_fill + lambert * diffuse_span;
            vec2 average_light_direction = normalize(
                center_light_vector0.xy * base_light_weight0
                    + center_light_vector1.xy * base_light_weight1
                    + center_light_vector2.xy * base_light_weight2
                    + center_light_vector3.xy * base_light_weight3
                    + vec2(0.00001)
            );
            float broad_weight = (
                base_light_weight0 * (1.0 - sc_light0_extra.x)
                + base_light_weight1 * (1.0 - sc_light1_extra.x)
                + base_light_weight2 * (1.0 - sc_light2_extra.x)
                + base_light_weight3 * (1.0 - sc_light3_extra.x)
            ) / total_light_weight;
            vec2 relative_form_position = v_tex_coord - u_sc_form_center;
            // Smooth saturation.  A linear ramp with hard clamps puts a
            // straight band across the character wherever it saturates,
            // because the shading stops changing on one side of the line
            // and keeps ramping on the other.  This keeps the same slope
            // through the middle and the same limits, without the corners.
            float directional_ramp = dot(relative_form_position, average_light_direction) * 1.8;
            float directional = 0.5 + 0.5 * (
                directional_ramp / sqrt(1.0 + directional_ramp * directional_ramp)
            );
            form_light *= 1.0 + (directional - 0.5) * 0.32 * key_amount * broad_weight;
            vec3 response0 = texture2D(tex5, clamp(center_light_vector0.xy * 0.5 + 0.5, vec2(0.0), vec2(1.0))).rgb;
            vec3 response1 = texture2D(tex5, clamp(center_light_vector1.xy * 0.5 + 0.5, vec2(0.0), vec2(1.0))).rgb;
            vec3 response2 = texture2D(tex5, clamp(center_light_vector2.xy * 0.5 + 0.5, vec2(0.0), vec2(1.0))).rgb;
            vec3 response3 = texture2D(tex5, clamp(center_light_vector3.xy * 0.5 + 0.5, vec2(0.0), vec2(1.0))).rgb;
            vec3 response = (
                response0 * base_light_weight0
                    + response1 * base_light_weight1
                    + response2 * base_light_weight2
                    + response3 * base_light_weight3
            ) / total_light_weight;
            float expected_lambert = mix(0.72, response.r, step(0.5, u_sc_has_form));
            float expected_form = diffuse_fill + expected_lambert * diffuse_span;
            form_light /= max(expected_form, 0.001);
            float form_visibility = 0.38 + 0.62 * material_response;
            form_light = 1.0 + (form_light - 1.0) * form_visibility;
            if (u_sc_has_form > 0.5) {
                float mean_after_visibility = 1.0
                    + (diffuse_fill * u_sc_mean_form_visibility + diffuse_span * response.g)
                        / max(expected_form, 0.001)
                    - u_sc_mean_form_visibility;
                form_light /= max(mean_after_visibility, 0.001);
            }
            form_light = mix(1.0, clamp(form_light, 0.22, 2.2), u_sc_strength);
            float occlusion = clamp(
                surface_ao * u_sc_calibration2.y * u_sc_strength
                + ray_shadow * 0.18 * u_sc_calibration2.x * u_sc_strength,
                0.0,
                0.72
            );
            occlusion *= 0.36 + 0.64 * material_response;

            vec3 ambient_tint = pow(
                clamp(ambient_chroma, vec3(0.55), vec3(1.9)),
                vec3(u_sc_calibration0.w * auto_amount * sc_environment_adaptation)
            );
            float sc_scene_chroma_span = max(
                ambient_chroma.r,
                max(ambient_chroma.g, ambient_chroma.b)
            ) - min(
                ambient_chroma.r,
                min(ambient_chroma.g, ambient_chroma.b)
            );
            float sc_extreme_scene_chroma = smoothstep(
                0.55,
                1.15,
                sc_scene_chroma_span
            );
            // Only extreme environment chroma is compressed. Typical
            // daylight/classroom transport stays exactly on the original path;
            // this is an energy guard for backgrounds whose baked grade is too
            // saturated to represent incident light literally.
            ambient_tint = pow(
                ambient_tint,
                vec3(mix(1.0, 0.25, sc_extreme_scene_chroma))
            );
            // Direct color belongs to the surfaces receiving that light.
            // Shaded surfaces retain the environment fill instead of acquiring
            // the same global tint as surfaces facing the source.
            vec3 direct_chroma = source_color_field / max(lambert, 0.001);
            float direct_fraction = lambert * diffuse_span
                / max(diffuse_fill + lambert * diffuse_span, 0.001);
            ambient_tint = mix(ambient_tint, pow(
                clamp(direct_chroma, vec3(0.34), vec3(2.85)),
                vec3(u_sc_calibration0.w * auto_amount * sc_environment_adaptation)
            ), direct_fraction);
            vec3 source_tint = vec3(1.0);
            // A broad colored region can be a painted surface or foliage.
            // Its measured color already contributes to ambient/probe light;
            // hue alone must not promote it to a second directional lamp.
            // Automatic separation needs a compact source or independently
            // measured emission. Explicit artistic separation is unchanged.
            float sc_source_support1 = scenelight_colored_source_support(
                sc_light0_data, sc_light0_color, sc_light0_extra, sc_light1_data, sc_light1_color);
            float sc_source_support2 = scenelight_colored_source_support(
                sc_light0_data, sc_light0_color, sc_light0_extra, sc_light2_data, sc_light2_color);
            float sc_source_support3 = scenelight_colored_source_support(
                sc_light0_data, sc_light0_color, sc_light0_extra, sc_light3_data, sc_light3_color);
            // The photographed, energy-balanced aggregate remains the normal
            // path. Automatic separation engages for two distinct hue-family
            // sources, or for one strong colored source separated from a
            // neutral physical key. The manual control can still force the
            // effect for intentionally stylized work.
            float sc_separation_evidence = max(
                scenelight_separation_pair_evidence(
                    sc_light1_data, sc_light1_color, sc_light1_extra,
                    sc_light2_data, sc_light2_color, sc_light2_extra, sc_layout_mix,
                    sc_source_support1, sc_source_support2
                ),
                max(
                    scenelight_separation_pair_evidence(
                        sc_light1_data, sc_light1_color, sc_light1_extra,
                        sc_light3_data, sc_light3_color, sc_light3_extra, sc_layout_mix,
                        sc_source_support1, sc_source_support3
                    ),
                    scenelight_separation_pair_evidence(
                        sc_light2_data, sc_light2_color, sc_light2_extra,
                        sc_light3_data, sc_light3_color, sc_light3_extra, sc_layout_mix,
                        sc_source_support2, sc_source_support3
                    )
                )
            );
            sc_separation_evidence = max(
                sc_separation_evidence,
                max(
                    scenelight_primary_creative_evidence(
                        sc_light0_data, sc_light0_color,
                        sc_light1_data, sc_light1_color, sc_light1_extra, sc_layout_mix,
                        sc_source_support1
                    ),
                    max(
                        scenelight_primary_creative_evidence(
                            sc_light0_data, sc_light0_color,
                            sc_light2_data, sc_light2_color, sc_light2_extra, sc_layout_mix,
                            sc_source_support2
                        ),
                        scenelight_primary_creative_evidence(
                            sc_light0_data, sc_light0_color,
                            sc_light3_data, sc_light3_color, sc_light3_extra, sc_layout_mix,
                            sc_source_support3
                        )
                    )
                )
            );
            float sc_adaptive_light_colors = u_sc_calibration4.z
                * sc_separation_evidence;
            float sc_individual_light_colors = clamp(
                max(u_sc_calibration4.y, sc_adaptive_light_colors) * u_sc_strength,
                0.0,
                2.0
            );
            if (sc_individual_light_colors > 0.0001) {
                float sc_manual_separation = step(0.0001, u_sc_calibration4.y);
                float sc_accepted_source1 = mix(sc_source_support1, 1.0, sc_manual_separation);
                float sc_accepted_source2 = mix(sc_source_support2, 1.0, sc_manual_separation);
                float sc_accepted_source3 = mix(sc_source_support3, 1.0, sc_manual_separation);
                sc_creative_weight1 *= sc_accepted_source1;
                sc_creative_weight2 *= sc_accepted_source2;
                sc_creative_weight3 *= sc_accepted_source3;
                // Creative mode gives every detected hue family equal artistic
                // standing, then separates their directional lobes. Realistic
                // mode above remains energy-weighted and fully additive.
                // Smooth positive lobes retain directional color separation.
                // Normalize them directly below; a low-temperature softmax
                // exaggerates small differences into hard color boundaries.
                float sc_creative_power = 1.0
                    + 1.5 * sc_individual_light_colors;
                float sc_creative_spread = clamp(
                    sc_individual_light_colors * 0.42,
                    0.0,
                    0.84
                );
                // The light vectors are already normalized in 3D. Retain
                // their forward component: normalizing XY again makes an
                // overhead/nearby source flip abruptly across its centre.
                vec2 sc_creative_direction0 = light0.xy;
                vec2 sc_creative_direction1 = light1.xy;
                vec2 sc_creative_direction2 = light2.xy;
                vec2 sc_creative_direction3 = light3.xy;
                // A flat sprite's reconstructed normals can all lean toward
                // the viewer.  Creative separation therefore also uses the
                // pixel's direction across the character silhouette, giving
                // distinct lamps distinct regions to paint.
                // Smoothed in the same way: the hard length floor used to
                // kink the direction field at a fixed radius from the
                // sprite centre.
                vec2 sc_form_direction = relative_form_position
                    / sqrt(dot(relative_form_position, relative_form_position) + 0.0064);
                // Keep the forward component: normalizing XY alone turns
                // even a tiny slope into a full-strength sideways direction,
                // producing sharp color seams as the slope crosses zero.
                vec2 sc_creative_surface = normalize(vec3(
                    normal.xy + sc_form_direction * sc_creative_spread * 1.35,
                    normal.z
                )).xy;
                float sc_creative_lobe0 = clamp(
                    0.50 + 0.50 * dot(sc_creative_surface, sc_creative_direction0), 0.035, 1.0
                );
                float sc_creative_lobe1 = clamp(
                    0.50 + 0.50 * dot(sc_creative_surface, sc_creative_direction1), 0.035, 1.0
                );
                float sc_creative_lobe2 = clamp(
                    0.50 + 0.50 * dot(sc_creative_surface, sc_creative_direction2), 0.035, 1.0
                );
                float sc_creative_lobe3 = clamp(
                    0.50 + 0.50 * dot(sc_creative_surface, sc_creative_direction3), 0.035, 1.0
                );
                float sc_creative_influence0 = pow(
                    mix(max(lambert0, 0.035), sc_creative_lobe0, sc_creative_spread)
                        * sc_creative_weight0,
                    sc_creative_power
                );
                float sc_creative_influence1 = pow(
                    mix(max(lambert1, 0.035), sc_creative_lobe1, sc_creative_spread)
                        * sc_creative_weight1,
                    sc_creative_power
                );
                float sc_creative_influence2 = pow(
                    mix(max(lambert2, 0.035), sc_creative_lobe2, sc_creative_spread)
                        * sc_creative_weight2,
                    sc_creative_power
                );
                float sc_creative_influence3 = pow(
                    mix(max(lambert3, 0.035), sc_creative_lobe3, sc_creative_spread)
                        * sc_creative_weight3,
                    sc_creative_power
                );
                // When hue-family sources are available, they are the
                // separated artistic lights.  Do not count the already-fused
                // physical key a second time or warm scenes collapse back to
                // a single orange tint.
                float sc_creative_source_count =
                    (sc_layout_mix < 0.0 ? 1.0 - step(0.001, sc_light1_data.w) : sc_layout_mix)
                        * smoothstep(0.0, 0.65, sc_light1_extra.x) * sc_accepted_source1
                    + (sc_layout_mix < 0.0 ? 1.0 - step(0.001, sc_light2_data.w) : sc_layout_mix)
                        * smoothstep(0.0, 0.65, sc_light2_extra.x) * sc_accepted_source2
                    + (sc_layout_mix < 0.0 ? 1.0 - step(0.001, sc_light3_data.w) : sc_layout_mix)
                        * smoothstep(0.0, 0.65, sc_light3_extra.x) * sc_accepted_source3;
                // With one colored source, retain the neutral aggregate in
                // this mix so the two sources paint different body regions.
                // With multiple hue families, omit the already-fused primary
                // exactly as before.
                float sc_multiple_creative_sources = smoothstep(
                    1.0, 2.0,
                    sc_creative_source_count
                );
                sc_creative_influence0 *= 1.0 - sc_multiple_creative_sources;
                // Direct weighted blending preserves zero contribution from
                // absent sources and lets neighbouring colored lights overlap.
                float sc_creative_total = max(
                    sc_creative_influence0 + sc_creative_influence1
                        + sc_creative_influence2 + sc_creative_influence3,
                    0.001
                );
                vec3 sc_separated_source_chroma = scenelight_unit_energy(
                    (
                        sc_creative_influence0 * sc_light0_color.rgb
                        + sc_creative_influence1 * sc_light1_color.rgb
                        + sc_creative_influence2 * sc_light2_color.rgb
                        + sc_creative_influence3 * sc_light3_color.rgb
                    ) / sc_creative_total
                );
                float sc_separated_source_mix = clamp(
                    sc_individual_light_colors * key_amount * (0.42 + 0.48 * lambert),
                    0.0,
                    0.95
                );
                source_tint = mix(
                    source_tint,
                    clamp(sc_separated_source_chroma, vec3(0.34), vec3(2.85)),
                    sc_separated_source_mix
                );
            }
            // Apply after physical color guards and source classification so a
            // stronger artistic cast cannot accidentally trigger their clamps.
            ambient_tint = scenelight_adjust_light_color(ambient_tint, u_sc_calibration8, u_sc_calibration4.w);
            source_tint = scenelight_adjust_light_color(source_tint, u_sc_calibration8, u_sc_calibration4.w);
            float sc_adjustment_strength = clamp(u_sc_strength, 0.0, 1.0);
            vec3 lit = base * input_exposure * mix(1.0, u_sc_calibration0.z, sc_adjustment_strength)
                * ambient_tint * source_tint * form_light * (1.0 - occlusion);

            // Colored shadow transport is independent from source tint. It
            // keeps the unlit side anchored to the measured environment
            // instead of multiplying the entire character by one scene hue.
            float shadow_mix = clamp((0.78 - lambert) * 0.56 * key_amount, 0.0, 0.52);
            shadow_mix *= 0.34 + 0.66 * material_response;
            shadow_mix *= u_sc_calibration4.x / 0.62;
            vec3 sc_shadow_tint = mix(
                vec3(1.0),
                clamp(shadow_chroma, vec3(0.55), vec3(1.75)),
                sc_environment_adaptation
            );
            sc_shadow_tint = scenelight_adjust_light_color(sc_shadow_tint, u_sc_calibration8, u_sc_calibration4.w);
            lit *= mix(vec3(1.0), sc_shadow_tint, shadow_mix);

            // The exact eight directional probes measured by the CPU scene
            // analysis are cheap uniforms; no four-sample background-color
            // approximation is needed on the GPU.
            vec3 probe_rgb = vec3(0.0);
            float probe_weight = 0.0;
            vec3 ground_rgb = vec3(0.0);
            float ground_energy = 0.0;
            float probe_local_reference = local_luminance + 0.025;
            vec4 transport_probe0 = scenelight_transport_at(15.0, v_sc_center);
            vec4 transport_probe1 = scenelight_transport_at(16.0, v_sc_center);
            vec4 transport_probe2 = scenelight_transport_at(17.0, v_sc_center);
            vec4 transport_probe3 = scenelight_transport_at(18.0, v_sc_center);
            vec4 transport_probe4 = scenelight_transport_at(19.0, v_sc_center);
            vec4 transport_probe5 = scenelight_transport_at(20.0, v_sc_center);
            vec4 transport_probe6 = scenelight_transport_at(21.0, v_sc_center);
            vec4 transport_probe7 = scenelight_transport_at(22.0, v_sc_center);
            vec3 transport_probe_scalar0 = scenelight_transport_at(23.0, v_sc_center).rgb;
            vec3 transport_probe_scalar1 = scenelight_transport_at(24.0, v_sc_center).rgb;
            vec3 transport_probe_scalar2 = scenelight_transport_at(25.0, v_sc_center).rgb;
            scenelight_accumulate_probe(
                mix(u_sc_probe0_data, vec4(-1.0, 0.0, transport_probe_scalar0.r, 1.0), transport_mix),
                mix(u_sc_probe0_color, transport_probe0.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe1_data, vec4(-0.7071, -0.7071, transport_probe_scalar0.g, 1.0), transport_mix),
                mix(u_sc_probe1_color, transport_probe1.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe2_data, vec4(0.0, -1.0, transport_probe_scalar0.b, 1.0), transport_mix),
                mix(u_sc_probe2_color, transport_probe2.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe3_data, vec4(0.7071, -0.7071, transport_probe_scalar1.r, 1.0), transport_mix),
                mix(u_sc_probe3_color, transport_probe3.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe4_data, vec4(1.0, 0.0, transport_probe_scalar1.g, 1.0), transport_mix),
                mix(u_sc_probe4_color, transport_probe4.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe5_data, vec4(0.7071, 0.7071, transport_probe_scalar1.b, 1.0), transport_mix),
                mix(u_sc_probe5_color, transport_probe5.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe6_data, vec4(0.0, 1.0, transport_probe_scalar2.r, 1.0), transport_mix),
                mix(u_sc_probe6_color, transport_probe6.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            scenelight_accumulate_probe(
                mix(u_sc_probe7_data, vec4(-0.7071, 0.7071, transport_probe_scalar2.g, 1.0), transport_mix),
                mix(u_sc_probe7_color, transport_probe7.rgb * u_sc_chroma_range, transport_mix),
                normal, probe_local_reference, probe_rgb, probe_weight, ground_rgb, ground_energy
            );
            vec3 probe_tint = probe_rgb / max(probe_weight, 0.001);
            probe_tint = scenelight_unit_energy(probe_tint);
            probe_tint = scenelight_adjust_light_color(probe_tint, u_sc_calibration8, u_sc_calibration4.w);
            probe_tint = mix(vec3(1.0), probe_tint, sc_environment_adaptation);
            float probe_mix = clamp(u_sc_calibration2.z * 0.16 * (probe_weight / 4.0), 0.0, 0.22) * u_sc_strength;
            lit *= mix(vec3(1.0), clamp(probe_tint, vec3(0.58), vec3(1.9)), probe_mix);

            // Low-frequency color below the final screen position provides a
            // restrained ground/floor bounce, strongest on the lower body.
            // Smoothstep between the same two heights, so the floor bounce
            // fades in and out instead of ending on a horizontal line.
            float lower_body_ramp = clamp((relative_form_position.y + 0.30) * 1.45, 0.0, 1.0);
            float lower_body = lower_body_ramp * lower_body_ramp * (3.0 - 2.0 * lower_body_ramp);
            float downward_facing = clamp(normal.y * 0.70 + (1.0 - normal.z) * 0.22, 0.0, 1.0);
            float bounce = (0.24 * lower_body + 0.76 * downward_facing)
                * u_sc_calibration2.w * 0.16 * u_sc_strength;
            vec3 ground_chroma = clamp(ground_rgb / max(ground_energy, 0.001), vec3(0.52), vec3(2.2));
            ground_chroma = scenelight_adjust_light_color(ground_chroma, u_sc_calibration8, u_sc_calibration4.w);
            ground_chroma = mix(vec3(1.0), ground_chroma, sc_environment_adaptation);
            lit += base * input_exposure * ground_chroma * bounce;

            float saturation = max(base_srgb.r, max(base_srgb.g, base_srgb.b)) - min(base_srgb.r, min(base_srgb.g, base_srgb.b));
            vec3 half0 = normalize(center_light_vector0 + vec3(0.0, 0.0, 1.0));
            vec3 half1 = normalize(center_light_vector1 + vec3(0.0, 0.0, 1.0));
            vec3 half2 = normalize(center_light_vector2 + vec3(0.0, 0.0, 1.0));
            vec3 half3 = normalize(center_light_vector3 + vec3(0.0, 0.0, 1.0));
            float specular_power = 22.0 + sc_live_sharpness * 34.0;
            vec3 specular_field = (
                pow(max(dot(normal, half0), 0.0), specular_power) * (1.0 - ray_shadow * u_sc_calibration2.x) * light0.w * sc_light0_color.rgb
                + pow(max(dot(normal, half1), 0.0), specular_power) * (1.0 - secondary_ray_shadow * u_sc_calibration2.x) * light1.w * sc_light1_color.rgb
                + pow(max(dot(normal, half2), 0.0), specular_power) * light2.w * sc_light2_color.rgb
                + pow(max(dot(normal, half3), 0.0), specular_power) * light3.w * sc_light3_color.rgb
            ) / total_light_weight;
            float dielectric = clamp(0.18 + (1.0 - saturation) * 0.82, 0.18, 1.0);
            float specular_material = dielectric * (0.14 + 0.86 * material_response);
            float sc_specular_luma = dot(specular_field, vec3(0.2126, 0.7152, 0.0722));
            specular_field = mix(
                vec3(sc_specular_luma),
                specular_field,
                sc_environment_adaptation
            );
            // Reconstructed normals can contain broad mathematical ridges on
            // otherwise flat painted regions. They remain useful for diffuse
            // form, but may create a sharp fake specular band unless the source
            // art has nearby structure capable of receiving that highlight.
            specular_field = scenelight_adjust_light_color(specular_field, u_sc_calibration8, u_sc_calibration4.w);
            lit += specular_field * specular_material * u_sc_calibration3.x * 0.13
                * form_detail_visibility * u_sc_strength * exposure;

            float fallback_edge = max(
                alpha - texture2D(
                    tex0,
                    clamp(v_tex_coord + light_direction * sprite_texel * 3.5, vec2(0.0), vec2(1.0)),
                    u_lod_bias
                ).a,
                0.0
            );
            float form_edge = mix(
                fallback_edge,
                texture2D(tex3, clamp(v_tex_coord, vec2(0.0), vec2(1.0))).b,
                step(0.5, u_sc_has_form)
            );
            float rim_facing = pow(max(dot(normal.xy, primary_light_vector.xy), 0.0), 0.7);
            float rim = form_edge * rim_facing * u_sc_calibration3.y * confidence * u_sc_strength;
            rim *= 0.12 + 0.88 * material_response;
            rim *= 0.42 + 0.58 * (1.0 - mix(u_sc_source_size, sc_light0_data.z, transport_mix));
            vec3 sc_rim_chroma = mix(
                vec3(1.0),
                clamp(sc_light0_color.rgb, vec3(0.55), vec3(2.2)),
                sc_environment_adaptation
            );
            sc_rim_chroma = scenelight_adjust_light_color(sc_rim_chroma, u_sc_calibration8, u_sc_calibration4.w);
            lit += sc_rim_chroma * rim * 0.52 * exposure;

            // In creative mode, secondary lights also receive a colored edge
            // response instead of being compressed into the primary rim. The
            // chroma is normalized before addition so saturated lamp colors do
            // not create an accidental exposure increase.
            if (sc_individual_light_colors > 0.0001) {
                float sc_rim_facing0 = rim_facing;
                float sc_rim_facing1 = pow(max(dot(normal.xy, light1.xy), 0.0), 0.7);
                float sc_rim_facing2 = pow(max(dot(normal.xy, light2.xy), 0.0), 0.7);
                float sc_rim_facing3 = pow(max(dot(normal.xy, light3.xy), 0.0), 0.7);
                float sc_multi_rim_weight = (
                    sc_rim_facing0 * sc_creative_weight0
                    + sc_rim_facing1 * sc_creative_weight1
                    + sc_rim_facing2 * sc_creative_weight2
                    + sc_rim_facing3 * sc_creative_weight3
                );
                vec3 sc_multi_rim_color = scenelight_unit_energy(
                    (
                        sc_rim_facing0 * sc_creative_weight0 * sc_light0_color.rgb
                        + sc_rim_facing1 * sc_creative_weight1 * sc_light1_color.rgb
                        + sc_rim_facing2 * sc_creative_weight2 * sc_light2_color.rgb
                        + sc_rim_facing3 * sc_creative_weight3 * sc_light3_color.rgb
                    ) / max(sc_multi_rim_weight, 0.001)
                );
                float sc_multi_rim = form_edge
                    * clamp(sc_multi_rim_weight / total_light_weight, 0.0, 1.0)
                    * u_sc_calibration3.y * confidence
                    * (0.12 + 0.88 * material_response)
                    * sc_individual_light_colors;
                sc_multi_rim_color = scenelight_adjust_light_color(sc_multi_rim_color, u_sc_calibration8, u_sc_calibration4.w);
                lit += clamp(sc_multi_rim_color, vec3(0.34), vec3(2.85))
                    * sc_multi_rim * 0.24 * exposure;
            }

            // Exact desktop environment wrap: only the distance-field edge
            // and semitransparent pixels receive the low-frequency scene
            // color. Interior paint is never replaced by the pixel directly
            // behind the character.
            vec3 environment_wrap = scenelight_srgb_to_linear(
                scenelight_wrap_at(v_sc_screen)
            );
            environment_wrap = scenelight_adjust_light_color(environment_wrap, u_sc_calibration8, u_sc_calibration4.w);
            float sc_wrap_luma = dot(environment_wrap, vec3(0.2126, 0.7152, 0.0722));
            environment_wrap = mix(
                vec3(sc_wrap_luma),
                environment_wrap,
                sc_environment_adaptation
            );
            float opaque_wrap = 0.12 + 0.88 * material_response;
            float wrap_weight = 0.25 * alpha * opaque_wrap + (1.0 - alpha);
            float wrap = clamp(form_edge * wrap_weight * u_sc_calibration3.z * u_sc_strength, 0.0, 0.64);
            lit = mix(lit, environment_wrap, wrap);

            // Preserve authored reflectance chroma on bright, nearly neutral
            // paint under the broad-diffuse camera condition above. The target
            // is normalized to the current generated luminance, so exposure,
            // normals, AO, self-shadow, rim, and motion remain unchanged.
            float sc_neutral_material = 1.0 - smoothstep(0.16, 0.36, saturation);
            float sc_bright_material = smoothstep(0.10, 0.38, base_luma);
            float sc_chroma_preservation = u_sc_calibration0.w
                * sc_chroma_guard
                * sc_neutral_material
                * sc_bright_material
                * auto_amount;
            float sc_preserved_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
            vec3 sc_source_chroma = clamp(
                base / max(base_luma, 0.001),
                vec3(0.55),
                vec3(1.80)
            );
            lit = mix(
                lit,
                sc_preserved_luma * sc_source_chroma,
                sc_chroma_preservation
            );

            // Match the CPU contrast stage around a palette-derived pivot.
            // This pivot changes only the contrast curve, never exposure.
            float precontrast_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
            float desired_contrast = clamp(0.84 + local_contrast * 0.35, 0.76, 1.24);
            float contrast_power = 1.0 + (
                (desired_contrast - 1.0) * u_sc_calibration1.x
                    * auto_amount * sc_environment_adaptation * u_sc_debug_contrast
            );
            float contrast_mid = max(u_sc_form_contrast_mid * exposure, 0.006);
            float contrast_ratio = pow(
                (precontrast_luma + 0.018) / (contrast_mid + 0.018),
                contrast_power - 1.0
            );
            lit *= clamp(contrast_ratio, 0.55, 1.70);

            // Scene saturation matching stays in linear light and never uses
            // the sprite's global palette as an exposure meter.
            float lit_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
            vec3 lit_gray = vec3(lit_luma);
            float target_sat_scale = clamp(0.72 + local_saturation * 1.05, 0.68, 1.30);
            // An almost colorless environment does not imply colorless paint.
            // Fade out desaturation when the scene has no chromatic evidence.
            if (target_sat_scale < 1.0) {
                target_sat_scale = 1.0 + (target_sat_scale - 1.0)
                    * smoothstep(0.04, 0.16, local_saturation);
            }
            float sat_scale = 1.0 + (target_sat_scale - 1.0)
                * u_sc_calibration1.y * auto_amount * sc_environment_adaptation;
            lit = lit_gray + (lit - lit_gray) * sat_scale;

            // Authored sprite emitters add light, without changing the scene's
            // detected sources or manufacturing a shadow on transparent pixels.
            vec3 sprite_emission = scenelight_sprite_light(u_sc_sprite_light0_data, u_sc_sprite_light0_color, normal, u_sc_screen_aspect)
                + scenelight_sprite_light(u_sc_sprite_light1_data, u_sc_sprite_light1_color, normal, u_sc_screen_aspect)
                + scenelight_sprite_light(u_sc_sprite_light2_data, u_sc_sprite_light2_color, normal, u_sc_screen_aspect)
                + scenelight_sprite_light(u_sc_sprite_light3_data, u_sc_sprite_light3_color, normal, u_sc_screen_aspect);
            lit += base * sprite_emission * u_sc_strength;

            // Compress new illumination above the painted pixel's own level.
            // Re-tonemapping an already exposed white shirt collapses its
            // painted folds even when lighting only darkens it. The source
            // sets the shoulder's start, never the scene exposure or output.
            float generated_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
            float sc_highlight_protection = u_sc_calibration1.z * sc_adjustment_strength;
            float shoulder_start = max(0.46, base_luma);
            float shoulder_excess = max(generated_luma - shoulder_start, 0.0);
            float shoulder_luma = shoulder_start + shoulder_excess / (
                1.0 + shoulder_excess * (1.7 * sc_highlight_protection)
            );
            lit *= shoulder_luma / max(generated_luma, shoulder_luma);
            float peak = max(lit.r, max(lit.g, lit.b));
            float peak_start = max(0.82, min(max(base.r, max(base.g, base.b)), 1.0));
            float peak_excess = max(peak - peak_start, 0.0);
            float compressed_peak = peak_start + peak_excess / (
                1.0 + peak_excess / max(1.0 - peak_start, 0.0001)
            );
            float gamut_strength = clamp(sc_highlight_protection / 1.2, 0.0, 1.0);
            lit *= mix(
                1.0,
                compressed_peak / max(peak, compressed_peak),
                step(peak_start, peak) * gamut_strength
            );

            // Optional effects are applied only after the approved physical
            // relighting result exists. Each branch is a strict identity when
            // its intensity is zero, preserving exact disabled parity.
            if (u_sc_rain_data.x > 0.0001 && alpha > 0.001) {
                float rain_intensity = u_sc_rain_data.x;
                float wetness = u_sc_rain_data.y;
                float rain_time = u_sc_effect_time * u_sc_rain_data.w;
                float streak = scenelight_fx_rain_streak(
                    v_tex_coord,
                    rain_time,
                    u_sc_rain_data.z,
                    u_sc_rain_color_scale.w
                );
                float upward_facing = clamp(normal.z * 0.72 - normal.y * 0.28, 0.0, 1.0);
                float wet_mask = clamp(
                    wetness * rain_intensity * (0.28 + 0.72 * upward_facing),
                    0.0,
                    1.0
                );
                lit *= 1.0 - wet_mask * 0.105;
                vec3 rain_color = scenelight_srgb_to_linear(u_sc_rain_color_scale.rgb);
                float wet_specular = pow(
                    max(dot(normal, normalize(primary_light_vector)), 0.0),
                    18.0
                );
                lit += rain_color * wet_specular * wet_mask * 0.34;
                lit += rain_color * streak * rain_intensity * (0.18 + 0.34 * form_edge);
            }

            if (sc_glitch_intensity > 0.0001 && alpha > 0.001) {
                float sc_line = 0.5 + 0.5 * sin(
                    (v_sc_screen.y * max(u_sc_sprite_size.y, 1.0) + u_sc_effect_time * 37.0) * 3.14159265359
                );
                lit *= 1.0 - u_sc_glitch_extra.y * sc_glitch_intensity * sc_line * 0.12;
                float sc_block = scenelight_fx_hash(
                    floor(v_tex_coord * vec2(24.0, 36.0) / max(u_sc_glitch_data.z, 0.25))
                    + floor(u_sc_effect_time * u_sc_glitch_data.w * 12.0)
                    + u_sc_glitch_extra.w
                );
                float sc_corrupt = step(0.90 - 0.25 * sc_glitch_intensity, sc_block);
                vec3 sc_luma = vec3(dot(lit, vec3(0.2126, 0.7152, 0.0722)));
                lit = mix(lit, sc_luma.bgr * vec3(0.82, 1.14, 1.28), sc_corrupt * 0.36);
                float sc_fragment = step(
                    u_sc_glitch_extra.z * sc_glitch_intensity * 0.24,
                    scenelight_fx_hash(
                        floor(v_tex_coord * vec2(160.0, 96.0))
                        + floor(u_sc_effect_time * 20.0)
                    )
                );
                alpha *= sc_fragment;
            }

            if (u_sc_has_form > 0.5 && sc_live_grain > 0.015) {
                float form_noise = (form_aux.b * 2.0 - 1.0) * u_sc_noise_range;
                float post_luma = dot(lit, vec3(0.2126, 0.7152, 0.0722));
                float grain_weight = clamp(1.0 - abs(post_luma - 0.35) * 1.8, 0.24, 1.0);
                lit += vec3(
                    form_noise * sc_live_grain * u_sc_calibration3.w * 0.018 * grain_weight * sc_adjustment_strength
                );
            }

                if (u_sc_glow_data.x > 0.0) {
                    // Emissive art remains luminous even in a dark environment.
                    lit = max(lit, base * (1.0 + 0.6 * u_sc_glow_data.x));
                    vec3 tinted_emission = scenelight_srgb_to_linear(u_sc_glow_color.rgb)
                        * dot(base, vec3(0.2126, 0.7152, 0.0722)) * (1.0 + 0.6 * u_sc_glow_data.x);
                    lit = mix(lit, tinted_emission, u_sc_glow_color.a);
                }
                vec3 output_srgb = scenelight_linear_to_srgb(clamp(lit, 0.0, 1.0));
                float original_view = step(0.5, u_sc_compare_mode)
                    * (1.0 - step(1.5, u_sc_compare_mode));
                original_view += step(1.5, u_sc_compare_mode)
                    * (1.0 - step(0.5, v_tex_coord.x));
                output_srgb = mix(output_srgb, base_srgb, original_view);
                float output_alpha = mix(alpha, source.a, original_view);
                gl_FragColor = vec4(output_srgb * output_alpha, output_alpha);
            } else {
                gl_FragColor = vec4(0.0);
            }
            if (u_sc_glow_data.x > 0.0 && u_sc_glow_data.y > 0.0) {
                float show_glow = 1.0 - step(0.5, u_sc_compare_mode)
                    + step(1.5, u_sc_compare_mode) * step(0.5, v_tex_coord.x);
                vec4 halo = scenelight_sprite_halo(tex0, u_lod_bias, v_tex_coord, u_sc_sprite_size, u_sc_glow_data, u_sc_glow_color) * show_glow;
                gl_FragColor += halo * (1.0 - gl_FragColor.a);
            }
        """,
}
