# SceneLight creative-handover probe.
#
# Drop this file into a game's "game" folder as zz_creative_handover_probe.rpy,
# point the three values below at the background and sprite you want to look at,
# then launch the game.  It renders one frame, saves it, and quits, so it needs
# no clicking and touches no save data.
#
# Visual companion to the automated OpenGL continuity regression. Use a real
# background and sprite to inspect colored-light handovers on artwork as well.
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
