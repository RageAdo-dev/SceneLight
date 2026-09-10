## Opt-in integration audit. Never linked from the game's normal UI.
init 999 python:
    import json as _audit_json
    import os as _audit_os
    _audit_root = _audit_os.environ.get("SCENELIGHT_TEMPORAL_AUDIT")
    if _audit_root:
        config.save_directory = "SceneLight-Temporal-Audit"
        config.label_overrides["splashscreen"] = "scenelight_temporal_audit"
        config.label_overrides["before_main_menu"] = "scenelight_temporal_audit"

    def _audit_nodes(root):
        pending, seen = [root], set()
        while pending and len(seen) < 256:
            node = pending.pop()
            if node is None or id(node) in seen:
                continue
            seen.add(id(node))
            yield node
            for attribute in ("child", "target", "displayable"):
                pending.append(getattr(node, attribute, None))
            pending.extend(getattr(node, "children", ()) or ())

    class _TemporalAudit(renpy.Displayable):
        def __init__(self, **kwargs):
            super(_TemporalAudit, self).__init__(**kwargs)
            self.last = -1
            self.rows = []
        def render(self, width, height, st, at):
            renpy.redraw(self, 0.0)
            tick = int(st * 30)
            if tick != self.last:
                self.last = tick
                row = {"st": st, "runtime": renpy.get_game_runtime(), "background": [], "fields": []}
                row["frozen"] = []
                row["stable"] = SCENELIGHT_STABLE_SCENE_KEY
                row["dict_type"] = str(dict)
                for entry in renpy.game.context().scene_lists.layers.get("master", ()):
                    if entry.tag == "bg":
                        row["name"] = list(entry.name)
                        row["show_time"] = entry.show_time
                        row["frame_time"] = renpy.game.interface.frame_time
                        selected = _scenelight_timed_scene(" ".join(entry.name[1:]), entry)
                        sequence = SCENELIGHT_SCENE_SEQUENCES.get(" ".join(entry.name[1:]))
                        row["sequence_type"] = str(type(sequence))
                        row["sequence_is_dict"] = isinstance(sequence, dict)
                        row["resolved"] = [k for k, v in SCENELIGHT_SCENES.items() if v is selected]
                        for node in _audit_nodes(entry.displayable):
                            filename = getattr(node, "filename", None)
                            if filename:
                                row["background"].append(str(filename))
                            # TransitionAnimation has no current-child member.
                            # Read its authored timing (the engine's own render
                            # implementation uses these exact images/delays).
                            if node.__class__.__name__ == "TransitionAnimation":
                                origin = entry.animation_time if node.anim_timebase else entry.show_time
                                seconds = max(0, renpy.game.interface.frame_time - (origin or renpy.game.interface.frame_time))
                                seconds %= sum(node.delays)
                                for image, delay in zip(node.images, node.delays):
                                    if seconds < delay:
                                        row["background"].extend(str(n.filename) for n in _audit_nodes(image) if getattr(n, "filename", None))
                                        break
                                    seconds -= delay
                            if node.__class__.__name__ == "Movie":
                                if "_scenelight_movie_position" in globals():
                                    row["movie_lighting_pos"] = _scenelight_movie_position(node.channel)
                                row["movie_pos"] = renpy.music.get_pos(channel=node.channel)
                                row["movie_file"] = renpy.music.get_playing(channel=node.channel)
                    else:
                        for node in _audit_nodes(entry.displayable):
                            if isinstance(node, SceneLightSprite):
                                row["frozen"].append(node._sc_snapshot_frozen)
                                scene = getattr(node, "_sc_last_rendered_scene", None)
                                names = [k for k, v in SCENELIGHT_SCENES.items() if v is scene]
                                row["fields"].extend(names)
                self.rows.append(row)
            return renpy.Render(1, 1)

    def _audit_capture(index):
        if _audit_root:
            renpy.screenshot(_audit_os.path.join(_audit_root, "%02d.png" % index))

    def _audit_finish():
        if _audit_root:
            with open(_audit_os.path.join(_audit_root, "observations.json"), "w") as stream:
                _audit_json.dump(_audit_displayable.rows, stream, indent=2)
        renpy.quit(relaunch=False, status=0)

    def _audit_video_frame():
        if _audit_root and _audit_os.environ.get("SCENELIGHT_AUDIT_VIDEO"):
            data = renpy.screenshot_to_bytes((960, 540))
            if data:
                index = len(_audit_displayable.rows)
                with open(_audit_os.path.join(_audit_root, "video-%05d.png" % index), "wb") as stream:
                    stream.write(data)

screen scenelight_temporal_observer():
    zorder 1000
    add _audit_displayable
    timer 0.20 repeat True action Function(_audit_video_frame)

label scenelight_temporal_audit:
    $ quick_menu = False
    $ _audit_displayable = _TemporalAudit()
    show screen scenelight_temporal_observer
    if _audit_os.environ.get("SCENELIGHT_AUDIT_EXTENDED"):
        jump scenelight_temporal_extended
    scene bg br_dynamic
    show monika 1a at t11
    $ renpy.pause(1.15, hard=True)
    $ _audit_capture(0)
    $ renpy.pause(4.8, hard=True)
    $ _audit_capture(1)
    if _audit_os.environ.get("SCENELIGHT_AUDIT_QUICK"):
        $ _audit_finish()
    show monika 1b at t11
    $ renpy.pause(2.0, hard=True)
    scene bg br_gif_frames
    show monika 1a at t11
    $ renpy.pause(6.0, hard=True)
    $ _audit_capture(2)
    scene bg br_atl_stairs
    show monika 1a at t11
    $ renpy.pause(6.0, hard=True)
    $ _audit_capture(3)
    scene bg br_yellow_movie
    show monika 1a at t11
    $ renpy.pause(11.0, hard=True)
    $ _audit_capture(4)
    scene bg br_net_static
    show monika 1a at t11
    $ renpy.pause(3.0, hard=True)
    $ _audit_capture(5)
    scene bg club_day
    show monika 1a at t11
    $ renpy.pause(1.0, hard=True)
    $ _audit_capture(6)
    $ _audit_finish()

label scenelight_temporal_extended:
    scene bg br_net_tv
    show monika 1a at t11
    $ renpy.pause(3.0, hard=True)
    $ _audit_capture(0)
    scene bg br_net_optical
    show monika 1a at t11
    $ renpy.pause(3.0, hard=True)
    $ _audit_capture(1)
    scene bg br_pool_movie
    show monika 1a at t11
    $ renpy.pause(11.0, hard=True)
    $ _audit_capture(2)
    play movie "mod_assets/backrooms/video/pool_drift.webm" loop
    scene bg br_manual_movie
    show monika 1a at t11
    $ renpy.pause(11.0, hard=True)
    $ _audit_capture(3)
    stop movie
    scene bg br_real_vhs_movie
    show monika 1a at t11
    $ renpy.pause(13.0, hard=True)
    $ _audit_capture(4)
    $ _audit_finish()
