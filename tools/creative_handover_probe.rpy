# SceneLight creative-handover probe.
#
# Drop this file into a game's "game" folder as zz_creative_handover_probe.rpy,
# point the three values below at the background and sprite you want to look at,
# then launch the game.  It renders one frame, saves it, and quits, so it needs
# no clicking and touches no save data.
#
# Why this exists: the separated-light path can only be judged on a real scene
# through the real renderer.  The Interaction mod's Sayori sprite over its
# "bg house" background reproduces the case users reported, and a numpy model of
# the shader does not agree with the engine, so this probe -- not a unit test --
# is the visual guard for the lamp handover.
#
# What to look for: the borders between the differently coloured lights should
# read as gradients across cloth, hair and skin.  A straight-edged panel, or a
# hard line running down a face or sleeve, means the handover has collapsed back
# into a winner-take-all partition.

define sl_probe_background = "bg house"
define sl_probe_sprite = "sayori tap"
define sl_probe_output = r"D:\SceneLight probe\creative-handover.png"

init -100 python:
    import os as _sl_probe_os

    _sl_probe_dir = os.path.dirname(sl_probe_output)
    if _sl_probe_dir and not os.path.isdir(_sl_probe_dir):
        os.makedirs(_sl_probe_dir)


label splashscreen:
    $ renpy.block_rollback()
    scene expression sl_probe_background
    show expression sl_probe_sprite
    $ renpy.pause(3.0, hard=True)
    $ renpy.screenshot(sl_probe_output)
    $ renpy.quit()
