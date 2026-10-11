# This file is an example. Copy the calls you need into your own story script.

init python:
    # Optional reusable rules. Automatic analysis remains the lighting base.
    scenelight.background(
        "bg rooftop sunset",
        exposure_bias=-0.18,
        color_adaptation=0.94,
        rim_strength=0.82,
    )
    scenelight.character("yuri", strength=0.94, highlight_rolloff=1.35)


label scenelight_author_example:
    # This could instead be placed once at the beginning of label start.
    $ scenelight.configure(strength=1.0, light_mode="physical")

    scene bg club_night
    $ scenelight.scene(exposure_bias=-0.35, rim_strength=0.78)
    show monika 1a at t11
    m "This scene uses a temporary authored adjustment."

    # Compressed exposure plus restrained separated source colors.
    $ scenelight.scene(light_mode="cinematic")
    m "Cinematic mode sits between physical and full separation."

    $ scenelight.off()
    show special_flat_art
    "SceneLight is disabled for this sequence."

    # Restore the automatic whole-mod, background, character, and image rules.
    $ scenelight.clear_scene()
    return
