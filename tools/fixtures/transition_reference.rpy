## Independent midpoint-image oracle for an oversized, moved, lit character.
init 1001 python:
    import os as _mid_os
    _mid_root = _mid_os.environ.get("SCENELIGHT_TRANSITION_REFERENCE")
    if _mid_root:
        config.save_directory = "SceneLight-Transition-Reference"
        config.label_overrides["splashscreen"] = "scenelight_transition_reference"
        config.label_overrides["before_main_menu"] = "scenelight_transition_reference"

    def _mid_capture(name):
        data = renpy.screenshot_to_bytes((1280, 720))
        if not data:
            raise RuntimeError("No transition reference pixels")
        with open(_mid_os.path.join(_mid_root, name + ".png"), "wb") as stream:
            stream.write(data)

    class _MidpointDissolve(renpy.Displayable):
        delay = 1.5
        def __init__(self, old_widget=None, new_widget=None, **properties):
            super(_MidpointDissolve, self).__init__(**properties)
            self.inner = renpy.display.transition.Dissolve(1.0, old_widget=old_widget, new_widget=new_widget)
        def visit(self):
            return [self.inner]
        def render(self, width, height, st, at):
            renpy.redraw(self, 0.0)
            return renpy.render(self.inner, width, height, 0.5, 0.5)
        def event(self, event, x, y, st):
            # Allow the test timer to capture the settled, fixed 50% result.
            return self.inner.new_widget.event(event, x, y, st)

transform scenelight_mid_left:
    xpos 0.25
    xanchor 0.5
    ypos 1.0
    yanchor 1.0
    zoom 0.8
    alpha 1.0

transform scenelight_mid_right:
    xpos 0.75
    xanchor 0.5
    ypos 1.0
    yanchor 1.0
    zoom 0.8
    alpha 1.0

screen scenelight_mid_observer():
    timer 0.7 action Function(_mid_capture, "midpoint")

label scenelight_transition_reference:
    $ quick_menu = False
    $ renpy.set_physical_size((1280, 720))
    $ scenelight_set_enabled(True)
    $ scenelight_set_strength(1.0)
    $ scenelight.scene(light_mode="physical")
    scene bg br_red
    show monika 1a at scenelight_mid_left
    $ renpy.pause(2.0, hard=True)
    $ _mid_capture("before")
    show screen scenelight_mid_observer
    scene bg br_pool
    show monika 1a at scenelight_mid_right
    with _MidpointDissolve
    hide screen scenelight_mid_observer
    $ renpy.pause(1.0, hard=True)
    $ _mid_capture("after")
    $ renpy.quit(relaunch=False, status=0)
