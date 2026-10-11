"""Run the shipped CLI and native engine without stubbing capture or rendering."""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw

parser = argparse.ArgumentParser()
parser.add_argument("--package", type=Path, required=True)
parser.add_argument("--sdk", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--mode", choices=["developer", "player"], required=True)
parser.add_argument("--python", type=Path)
parser.add_argument("--lifecycle", action="store_true", help="Also test rollback and removal")
args = parser.parse_args()
root = args.output.resolve()
root.mkdir(parents=True, exist_ok=False)
project = root / "project"
game = project / "game"
images = game / "images"
images.mkdir(parents=True)
(root / "temp").mkdir()
environment = dict(
    os.environ,
    LOCALAPPDATA=str(root / "state/local"),
    APPDATA=str(root / "state/roaming"),
    SCENELIGHT_MANAGED_ROOT=str(root / "state/projects"),
    TEMP=str(root / "temp"),
    TMP=str(root / "temp"),
    SDL_AUDIODRIVER="dummy",
    RENPY_RENDERER="gl2",
)
python = args.python or args.package / "_scenelight/python/python.exe"
results = []


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def picture(name, color):
    image = Image.new("RGBA", (192, 288))
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 10, 135, 85), fill=(222, 180, 150, 255))
    draw.rounded_rectangle((30, 80, 165, 283), radius=18, fill=color)
    image.save(images / name)


def background(name, color):
    image = Image.new("RGB", (640, 360), color)
    ImageDraw.Draw(image).ellipse((20, 15, 210, 210), fill=(225, 180, 105))
    image.save(images / name)


for name, color in [
    ("hero.png", (70, 120, 160, 255)),
    ("companion.png", (120, 75, 140, 255)),
    ("excluded.png", (90, 90, 90, 255)),
]:
    picture(name, color)
background("room.png", (35, 60, 90))
(game / "script.rpy").write_text(
    """define config.screen_width = 1280
define config.screen_height = 720
define config.save_directory = None
define config.name = "SceneLight update rehearsal"
default qa_progress = 0
define hero_speaker = Character("Hero", image="hero")
define companion_speaker = Character("Companion", image="companion")
define excluded_speaker = Character("Excluded", image="excluded")
image bg room = "images/room.png"
image hero idle = "images/hero.png"
image excluded idle = "images/excluded.png"
layeredimage companion:
    always "images/companion.png"
    group facial:
        attribute idle default:
            Null()
init 10 python:
    if "scenelight" in globals():
        scenelight.character("hero", strength=0.43, exposure_bias=-0.35)
        scenelight.image("hero idle", strength=0.67, rim_strength=0.21)
init 1005 python:
    import os as qa_os
    import json as qa_json
    config.savedir = qa_os.path.join(config.basedir, "game", "saves")
    def qa_write_result():
        value = {"progress":qa_progress,"report":scenelight.inspect(),
            "loaded":bool(getattr(renpy.display,"_qa_reloaded",False)),
            "setup_count":getattr(renpy.display,"_qa_setup_count",0),
            "renpy":renpy.version()}
        with open(qa_os.environ["SL_RELEASE_RESULT"],"w") as stream:
            qa_json.dump(value,stream,indent=2)
    def qa_step(value):
        with open(qa_os.environ["SL_RELEASE_RESULT"] + ".steps", "a") as stream:
            stream.write(value + "\\n")
screen main_menu():
    if qa_os.environ.get("SL_RELEASE_PROBE"):
        timer 0.1 action Start("qa_" + qa_os.environ["SL_RELEASE_PROBE"] if qa_os.environ["SL_RELEASE_PROBE"] in ("rollback", "vanilla") else "qa_probe")
    else:
        textbutton "Start" action Start()
label qa_probe:
    $ qa_step("probe entered")
    scene bg room
    show hero idle
    show companion idle
    $ scenelight_set_strength(0.8)
    if qa_os.environ["SL_RELEASE_PROBE"] != "load":
        $ qa_progress = 73
    $ renpy.pause(0.5,hard=True,checkpoint=True)
    $ qa_step("pause completed")
    $ renpy.checkpoint()
    if getattr(renpy.display,"_qa_reloaded",False):
        $ qa_write_result()
        $ renpy.quit(relaunch=False,status=0)
    if qa_os.environ["SL_RELEASE_PROBE"] == "load":
        $ renpy.display._qa_reloaded = True
        $ renpy.load("update-rehearsal")
    $ qa_step("saving")
    $ renpy.save("update-rehearsal")
    $ qa_step("saved")
    $ qa_write_result()
    $ renpy.quit(relaunch=False,status=0)
label start:
    if qa_os.environ.get("SL_RELEASE_PROBE"):
        if qa_os.environ["SL_RELEASE_PROBE"] == "rollback":
            jump qa_rollback
        if qa_os.environ["SL_RELEASE_PROBE"] == "vanilla":
            jump qa_vanilla
        jump qa_probe
    scene bg room
    show hero idle
    show companion idle
    "Update rehearsal."
    return
screen qa_auto_advance():
    timer 0.1 repeat True action Function(renpy.end_interaction, True)
label qa_rollback:
    scene bg room
    show hero idle
    $ renpy.display._qa_setup_count = getattr(renpy.display, "_qa_setup_count", 0) + 1
    $ qa_progress = 11
    $ scenelight.image("hero idle", strength=0.4)
    show screen qa_auto_advance
    "Original lighting checkpoint."
    if getattr(renpy.display, "_qa_did_rollback", False):
        $ qa_write_result()
        $ renpy.quit(relaunch=False, status=0)
    $ qa_progress = 99
    $ scenelight.image("hero idle", strength=0.9)
    "Changed lighting checkpoint."
    $ renpy.display._qa_did_rollback = True
    $ renpy.rollback(force=True, checkpoints=1, greedy=False)
label qa_vanilla:
    scene bg room
    show hero idle
    $ renpy.pause(0.2, hard=True)
    python:
        with open(qa_os.environ["SL_RELEASE_RESULT"], "w") as stream:
            qa_json.dump({"runtime_removed": "scenelight" not in globals(), "renpy": renpy.version()}, stream)
    $ renpy.quit(relaunch=False, status=0)
""",
    encoding="utf-8",
)
config = project / "scenelight.json"
config.write_text(
    json.dumps(
        {
            "strength": 0.71,
            "calibration": {"exposure_bias": -0.12, "color_adaptation": 0.64},
            "auto_include_new_characters": True,
            "character_selection": "automatic",
            "excluded_character_tags": ["excluded"],
        }
    )
)
original_config = config.read_bytes()
(game / "saves").mkdir()
marker = game / "saves/player-notes.txt"
marker.write_text("Player files must survive.")


def run(name, command, env=environment, timeout=300):
    start = time.perf_counter()
    print(args.mode + " " + name + ": started", flush=True)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    with (root / (name + ".log")).open("wb") as log:
        completed = subprocess.run(
            [str(x) for x in command],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            startupinfo=startup,
        )
    duration = round(time.perf_counter() - start, 3)
    assert completed.returncode == 0, (
        name,
        completed.returncode,
        (root / (name + ".log")).read_text(errors="replace")[-7000:],
    )
    results.append({"step": name, "seconds": duration})
    print(args.mode + " " + name + ": passed in " + str(duration) + "s", flush=True)


def install(name, command):
    run(
        name,
        [
            python,
            "-m",
            "scenelight.cli",
            command,
            "--project",
            project,
            "--config",
            config,
            "--renpy-sdk",
            args.sdk,
            "--workers",
            "2",
            "--analyzer",
            "cpu",
        ],
    )


command = "embed" if args.mode == "developer" else "install"
update = "refresh" if args.mode == "developer" else "install"
install("initial-install", command)
if args.mode == "developer":
    installed = project
else:
    candidates = list((root / "state/projects").glob("*"))
    installed = next(p for p in candidates if (p / ".scenelight_install.json").is_file())
data = installed / "game/scenelight_runtime"
before = json.loads((data / "sprite_form_manifest.json").read_text())
map_hashes = {
    path.relative_to(data).as_posix(): digest(path)
    for path in (data / "sprite_form").rglob("*.png")
}


def native_probe(name, mode):
    output = root / (name + ".json")
    run(
        name,
        [args.sdk, installed],
        env=dict(
            environment,
            SL_RELEASE_PROBE=mode,
            SL_RELEASE_RESULT=str(output),
            RENPY_SKIP_MAIN_MENU="1",
        ),
        timeout=45,
    )
    assert output.is_file(), "Native probe did not write fresh evidence"
    value = json.loads(output.read_text())
    assert value["progress"] == 73, {"progress": value["progress"], "loaded": value["loaded"]}
    hero = next(s for s in value["report"]["sprites"] if s["image"] == "hero idle")
    assert hero["mapped_form"] and abs(hero["effective_strength"] - 0.536) < 1e-6, hero
    assert hero["values"]["exposure_bias"] == -0.35 and hero["values"]["rim_strength"] == 0.21
    if mode == "load":
        assert value["loaded"]
    return value


native_probe("native-save-before", "save")
save_hashes = {
    p.relative_to(installed).as_posix(): digest(p)
    for p in (installed / "game/saves").glob("*.save")
}
assert save_hashes, "Native save was not created"
install("unchanged-update", update)
text = (root / "unchanged-update.log").read_text(encoding="utf-8")
assert '"update_mode": "unchanged"' in text, text[-5000:]
assert map_hashes == {
    path.relative_to(data).as_posix(): digest(path)
    for path in (data / "sprite_form").rglob("*.png")
}

picture("newcomer.png", (155, 100, 45, 255))
background("garden.png", (65, 100, 50))
with (game / "script.rpy").open("a", encoding="utf-8") as stream:
    stream.write(
        '\ndefine newcomer_speaker = Character("Newcomer", image="newcomer")\nimage newcomer idle = "images/newcomer.png"\nimage bg garden = "images/garden.png"\nlabel qa_new_scene:\n    scene bg garden\n    show newcomer idle\n    return\n'
    )
install("one-new-sprite-background", update)
after = json.loads((data / "sprite_form_manifest.json").read_text())
manifest = json.loads((data / "manifest.json").read_text())
report = json.loads((data / "install_report.json").read_text())
assert "newcomer idle" in after["sprites"], list(after["sprites"])
assert "garden" in manifest["scenes"] and "room" in manifest["scenes"]
assert "excluded" not in manifest["character_tags"]
assert report["background_cache"]["fields_reused"] >= 1, report
assert report["background_cache"]["fields_analyzed"] == 1, report
assert report["sprite_cache"]["reused"] >= len(before["sprites"]), report
for name, digest_before in map_hashes.items():
    assert digest(data / name) == digest_before, name
assert config.read_bytes() == original_config
assert marker.read_text() == "Player files must survive."
assert all(digest(installed / name) == value for name, value in save_hashes.items())
native_probe("native-load-after", "load")
install("unchanged-after-playing", update)
assert '"update_mode": "unchanged"' in (root / "unchanged-after-playing.log").read_text(
    encoding="utf-8"
)
result = {
    "mode": args.mode,
    "engine": str(args.sdk),
    "package": str(args.package),
    "installer_python": str(python),
    "steps": results,
    "background_cache": report["background_cache"],
    "sprite_cache": report["sprite_cache"],
    "settings_preserved": True,
    "real_save_loaded": True,
    "unchanged_maps_preserved": len(map_hashes),
}
if args.lifecycle:
    output = root / "native-rollback.json"
    run(
        "native-rollback",
        [args.sdk, installed],
        env=dict(
            environment,
            SL_RELEASE_PROBE="rollback",
            SL_RELEASE_RESULT=str(output),
            RENPY_SKIP_MAIN_MENU="1",
        ),
        timeout=45,
    )
    value = json.loads(output.read_text())
    assert value["progress"] == 11, value
    assert value["setup_count"] == 1, "Rollback replayed setup instead of restoring state"
    hero = next(s for s in value["report"]["sprites"] if s["image"] == "hero idle")
    assert abs(hero["values"]["strength"] - 0.4) < 1e-6, hero
    authored = {
        str(p): digest(p) for p in [game / "script.rpy", *images.glob("*.png"), config, marker]
    }
    run(
        "remove",
        [
            python,
            "-m",
            "scenelight.cli",
            "unembed" if args.mode == "developer" else "remove",
            "--project",
            project,
        ],
    )
    assert all(digest(Path(path)) == value for path, value in authored.items())
    assert not (project / "game/scenelight_runtime").exists()
    if args.mode == "developer":
        assert all(digest(installed / name) == value for name, value in save_hashes.items())
    else:
        assert not installed.exists()
    output = root / "native-after-removal.json"
    run(
        "native-after-removal",
        [args.sdk, project],
        env=dict(
            environment,
            SL_RELEASE_PROBE="vanilla",
            SL_RELEASE_RESULT=str(output),
            RENPY_SKIP_MAIN_MENU="1",
        ),
        timeout=45,
    )
    assert json.loads(output.read_text())["runtime_removed"]
    result.update(
        rollback_restored_lighting=True, removal_preserved_source=True, vanilla_game_launched=True
    )
(root / "RESULT.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2), flush=True)
