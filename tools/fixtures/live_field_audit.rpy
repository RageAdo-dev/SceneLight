init 1005 python:
    import os as _field_os
    _field_root = _field_os.environ.get("SCENELIGHT_LIVE_FIELD_AUDIT")
    if _field_root:
        import json as _field_json
        config.save_directory = "SceneLight-Live-Field-Audit"
        config.label_overrides["splashscreen"] = "scenelight_live_field_audit"
        config.label_overrides["before_main_menu"] = "scenelight_live_field_audit"

        def _field_capture(name):
            renderer = renpy.display._scenelight_live_renderer
            fields = _scenelight_live_fields(_scenelight_live_scene())
            if not fields:
                raise RuntimeError("Expected live fields for " + name)
            device = renderer.analysis.device
            gpu, gl = renderer.gpu, device.gl
            draw = renpy.display.draw
            saved_fbo = draw.current_fbo
            sizes = {}
            try:
                with gpu.State(gl):
                    for entry in renpy.game.context().scene_lists.layers.get("master", ()):
                        if not isinstance(entry.displayable, _SceneLightBackground):
                            continue
                        background = entry.displayable
                        source_render = renderer.backgrounds[background.binding][0][0]
                        canvas = renpy.Render(config.screen_width, config.screen_height)
                        background.child.place(canvas, 0, 0, config.screen_width, config.screen_height, source_render)
                        canvas.xclipping = canvas.yclipping = True
                        if renderer.texture_transform is None:
                            draw.load_all_textures(canvas)
                        else:
                            draw.load_all_textures(canvas, renderer.texture_transform)
                        source = draw.render_to_texture(canvas, properties={"drawable_resolution": False, "mipmap": False})
                        break
                    for field, texture in list(fields.items()) + [("source", source)]:
                        width, height = texture.texture_width, texture.texture_height
                        sizes[field] = (width, height)
                        device.bind_targets((texture.number,))
                        pixels = (gpu.C.c_ubyte * (width * height * 4))()
                        gl.ReadPixels(0, 0, width, height, gpu.RGBA, gpu.UNSIGNED_BYTE, gpu.C.cast(pixels, gpu.GLvoidp))
                        with open(_field_os.path.join(_field_root, name + "-" + field + ".rgba"), "wb") as stream:
                            stream.write(gpu.C.string_at(pixels, len(pixels)))
            finally:
                draw.current_fbo = saved_fbo
            with open(_field_os.path.join(_field_root, name + ".json"), "w") as stream:
                _field_json.dump(sizes, stream)

label scenelight_live_field_audit:
    $ quick_menu = False
    scene bg br_pool
    show monika 1a at t11
    $ renpy.pause(1.0, hard=True)
    $ _field_capture("br_pool")
    scene bg br_red
    show monika 1a at t11
    $ renpy.pause(1.0, hard=True)
    $ _field_capture("br_red")
    scene bg club_day
    show monika 1a at t11
    $ renpy.pause(1.0, hard=True)
    $ _field_capture("club_day")
    $ renpy.quit(relaunch=False, status=0)
