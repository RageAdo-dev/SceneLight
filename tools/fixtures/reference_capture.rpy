## Opt-in visual reference capture. Install only in a disposable Backrooms copy.
init 999 python:
    import os as _ref_os
    _ref_root = _ref_os.environ.get("SCENELIGHT_REFERENCE_CAPTURE")
    if _ref_root:
        config.save_directory = "SceneLight-Reference-" + _ref_os.path.basename(_ref_root)
        config.label_overrides["splashscreen"] = "scenelight_reference_capture"
        config.label_overrides["before_main_menu"] = "scenelight_reference_capture"

    def _ref_capture(name):
        data = renpy.screenshot_to_bytes((1280, 720))
        if not data:
            raise RuntimeError("Renderer produced no reference pixels")
        with open(_ref_os.path.join(_ref_root, name + ".png"), "wb") as stream:
            stream.write(data)

transform scenelight_reference_placement:
    xpos 0.5
    xanchor 0.5
    ypos 1.0
    yanchor 1.0
    zoom 0.8
    alpha 1.0

label scenelight_reference_capture:
    $ quick_menu = False
    $ renpy.set_physical_size((1280, 720))
    $ renpy.pause(0.25, hard=True)
    $ scenelight_set_enabled(True)
    $ scenelight_set_strength(1.0)
    scene bg club_day
    show monika 1a at scenelight_reference_placement
    $ renpy.pause(1.5, hard=True)
    $ _ref_modes = ["physical", "cinematic", "separate"]
    $ _ref_index = 0
    while _ref_index < len(_ref_modes):
        $ _ref_mode = _ref_modes[_ref_index]
        $ scenelight.scene(light_mode=_ref_mode)
        scene bg club_day
        show monika 1a at scenelight_reference_placement
        $ renpy.pause(1.0, hard=True)
        $ _ref_capture(_ref_mode + "-classroom")
        scene bg br_red
        show monika 1a at scenelight_reference_placement
        $ renpy.pause(0.5, hard=True)
        $ _ref_capture(_ref_mode + "-red")
        scene bg br_pool
        show monika 1a at scenelight_reference_placement
        $ renpy.pause(0.5, hard=True)
        $ _ref_capture(_ref_mode + "-pool")
        $ _ref_index += 1
    $ renpy.quit(relaunch=False, status=0)
