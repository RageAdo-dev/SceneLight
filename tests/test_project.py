import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from scenelight.project import SpriteSpec, discover_project


def make_project(root: Path) -> Path:
    game = root / "game"
    (game / "images").mkdir(parents=True)
    background = Image.new("RGB", (320, 180), (18, 35, 70))
    draw = ImageDraw.Draw(background)
    draw.ellipse((20, 15, 105, 100), fill=(255, 130, 45))
    draw.rectangle((220, 0, 245, 180), fill=(75, 160, 255))
    background.save(game / "images" / "lab.png")
    sprite = Image.new("RGBA", (128, 192), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    draw.ellipse((32, 8, 96, 72), fill=(235, 184, 158, 255))
    draw.rounded_rectangle((20, 65, 108, 190), 24, fill=(220, 68, 116, 255))
    sprite.save(game / "images" / "nova.png")
    (game / "script.rpy").write_text(
        """define n = Character("Nova", image="nova")
image bg lab = "images/lab.png"
image nova idle = "images/nova.png"

label start:
    scene bg lab
    show nova idle at center
    n "Hello."
    return
""",
        encoding="utf-8",
    )
    return root


def test_live_scene_analysis_is_default_and_cached_mode_is_explicit(tmp_path):
    import json

    project = make_project(tmp_path)
    assert discover_project(project).scene_analysis == "live"
    profile = tmp_path / "test-profile.json"
    profile.write_text(json.dumps({"scene_analysis": "cached"}))
    assert discover_project(project, config_path=profile).scene_analysis == "cached"
    profile.write_text(json.dumps({"scene_analysis": []}))
    with pytest.raises(ValueError, match="scene_analysis"):
        discover_project(project, config_path=profile)


def test_positioned_runtime_sprite_composes_with_renderer_alpha(tmp_path: Path) -> None:
    base = tmp_path / "base.png"
    overlay = tmp_path / "overlay.png"
    base_image = Image.new("RGBA", (2, 1))
    base_image.putdata([(40, 80, 120, 128), (100, 110, 120, 255)])
    base_image.save(base)
    overlay_image = Image.new("RGBA", (1, 1), (200, 20, 60, 192))
    overlay_image.save(overlay)

    sprite = SpriteSpec(
        "hero layered",
        (base, overlay),
        positions=((0, 0), (1, 0)),
        canvas_size=(2, 1),
        renderer_alpha=True,
    ).compose()

    assert list(sprite.getdata()) == [(20, 40, 60, 64), (174, 41, 74, 254)]


def test_discovers_generic_character_and_scene(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    discovery = discover_project(project)
    assert list(discovery.scenes) == ["lab"]
    assert list(discovery.sprites) == ["nova idle"]
    assert discovery.character_tags == ["nova"]
    assert discovery.unsupported == []


def test_discovers_declared_and_manual_movie_sources(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    game = project / "game"
    declared_movie = game / "images" / "declared.webm"
    manual_movie = game / "images" / "manual.webm"
    declared_movie.write_bytes(b"declared")
    manual_movie.write_bytes(b"manual")
    script = game / "script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8")
        + """
image bg movie_room = Movie(
    play="images/declared.webm",
    loop=True,
    image="bg lab"
)
image bg manual_room = Movie(image="bg lab")

label movies:
    scene bg movie_room
    play movie "images/manual.webm" loop
    scene bg manual_room
    stop movie
    return
""",
        encoding="utf-8",
    )

    discovery = discover_project(project)

    assert discovery.scene_media == {
        "manual_room": manual_movie.resolve(),
        "movie_room": declared_movie.resolve(),
    }


def test_movie_declarations_handle_inline_nested_and_quoted_parentheses(tmp_path):
    project = make_project(tmp_path / "project")
    game = project / "game"
    video = game / "images" / "clip (1).mp4"
    video.write_bytes(b"movie")
    script = game / "script.rpy"
    with script.open("a", encoding="utf-8") as stream:
        stream.write("""
image bg inline = Movie(size=(1280, 720), play="images/clip (1).mp4")
image bg nested = Movie(
    size=(1280, 720), play="images/clip (1).mp4")
image bg dynamic = Movie(play=choose_movie())
label inline_movies:
    scene bg inline
    scene bg nested
    scene bg dynamic
    return
""")
    discovery = discover_project(project)
    assert discovery.scene_media == {"inline": video.resolve(), "nested": video.resolve()}


def test_config_adds_dynamic_content(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    (project / "scenelight.json").write_text(
        '{"scenes":{"lab_alias":"images/lab.png"},"character_tags":["nova"]}',
        encoding="utf-8",
    )
    discovery = discover_project(project)
    assert "lab_alias" in discovery.scenes


def test_external_calibration_merges_with_project_asset_config(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    (project / "scenelight.json").write_text(
        '{"scenes":{"lab_alias":"images/lab.png"},"character_tags":["nova"]}',
        encoding="utf-8",
    )
    profile = tmp_path / "profile.json"
    profile.write_text(
        '{"calibration_version":1,"strength":0.72,'
        '"calibration":{"exposure_bias":-0.25},'
        '"scene_calibration":{"lab":{"rim_strength":0.4}}}',
        encoding="utf-8",
    )

    discovery = discover_project(project, profile)

    assert "lab_alias" in discovery.scenes
    assert discovery.calibration.exposure_bias == -0.25
    assert discovery.strength == 0.72
    assert discovery.scene_calibration["lab"].rim_strength == 0.4
    assert discovery.scene_calibration["lab"].exposure_bias == -0.25


def test_discovers_layeredimage_runtime_forms(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    script = project / "game" / "script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8")
        + """
layeredimage nova forward:
    always "images/nova.png"
    group face:
        attribute smile default:
            "images/nova.png"

label layered_test:
    show nova forward smile
    n smile "Dialogue attributes also update the image."
    return
""",
        encoding="utf-8",
    )

    discovery = discover_project(project)

    assert "nova forward" in discovery.runtime_sprite_names
    assert "nova forward smile" in discovery.runtime_sprite_names
    assert "nova smile" in discovery.runtime_sprite_names
    assert any(
        "show nova forward smile" in sequence for sequence in discovery.runtime_sprite_sequences
    )
    assert any("show nova smile" in sequence for sequence in discovery.runtime_sprite_sequences)
    assert len(discovery.runtime_sprite_sequences) >= 2
    assert discovery.requires_runtime_inventory is False


def test_infers_character_tag_from_attributed_show_without_character_image(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path / "project")
    script = project / "game" / "script.rpy"
    script.write_text(
        """define n = Character("Nova")
image bg lab = "images/lab.png"
image nova idle = "images/nova.png"
image chapter card = "images/lab.png"

label start:
    scene bg lab
    show chapter card at truecenter
    show nova idle at center
    n "Hello."
    return
""",
        encoding="utf-8",
    )

    discovery = discover_project(project)

    assert discovery.character_tags == ["nova"]
    assert list(discovery.sprites) == ["nova idle"]
    assert "chapter" not in discovery.character_tags


def test_repeated_transparent_stickers_are_not_inferred_as_characters(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    game = project / "game"
    background = Image.new("RGB", (1280, 720), (20, 24, 30))
    background.save(game / "images" / "lab.png")
    sticker = Image.new("RGBA", (122, 173), (0, 0, 0, 0))
    ImageDraw.Draw(sticker).ellipse((8, 6, 114, 168), fill=(245, 130, 170, 255))
    sticker.save(game / "images" / "sticker.png")
    script = game / "script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8")
        + """
image nova_sticker happy = "images/sticker.png"

label sticker_page:
    show nova_sticker happy
    hide nova_sticker
    show nova_sticker happy
    return
""",
        encoding="utf-8",
    )

    discovery = discover_project(project)

    assert "nova_sticker" not in discovery.character_tags
    assert "nova_sticker happy" not in discovery.sprites


def test_config_can_explicitly_opt_in_small_stylized_character(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    game = project / "game"
    sticker = Image.new("RGBA", (122, 173), (0, 0, 0, 0))
    ImageDraw.Draw(sticker).ellipse((8, 6, 114, 168), fill=(245, 130, 170, 255))
    sticker.save(game / "images" / "chibi.png")
    script = game / "script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8")
        + '\nimage chibi happy = "images/chibi.png"\nshow chibi happy\n',
        encoding="utf-8",
    )
    (project / "scenelight.json").write_text(
        '{"character_tags":["chibi"]}',
        encoding="utf-8",
    )

    discovery = discover_project(project)

    assert "chibi" in discovery.character_tags
    assert "chibi happy" in discovery.sprites
    assert discovery.explicit_character_tags == ["chibi"]


def test_manual_character_selection_replaces_automatic_inference(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    profile = tmp_path / "profile.json"
    profile.write_text(
        '{"character_selection":"manual","character_tags":["guest"]}',
        encoding="utf-8",
    )

    discovery = discover_project(project, profile)

    assert discovery.character_selection == "manual"
    assert discovery.character_tags == ["guest"]
    assert discovery.sprites == {}
    assert discovery.character_candidates["nova"].endswith("nova.png")


@pytest.mark.parametrize("auto_include", [True, False])
def test_added_families_follow_policy_and_explicit_exclusions(tmp_path, auto_include):
    project = make_project(tmp_path / "project")
    script = project / "game" / "script.rpy"
    script.write_text(
        script.read_text()
        + '\ndefine g = Character("Guest", image="guest")\n'
        + 'image guest idle = "images/nova.png"\n'
        + '\ndefine b = Character("Blocked", image="blocked")\n'
        + 'image blocked idle = "images/nova.png"\nshow guest idle\nshow blocked idle\n'
    )
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "auto_include_new_characters": auto_include,
                "character_tags": ["nova"],
                "excluded_character_tags": ["blocked"],
            }
        )
    )
    discovery = discover_project(project, profile)
    assert discovery.character_tags == (["guest", "nova"] if auto_include else ["nova"])
    assert "blocked" in discovery.suggested_character_tags
    assert "blocked" in discovery.character_candidates
    assert all(not name.startswith("blocked ") for name in discovery.sprites)
    assert discovery.summary()["auto_include_new_characters"] is auto_include


def test_manual_selection_includes_selected_forms_not_reached_by_static_story_scan(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path / "project")
    script = project / "game" / "script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8") + '\nimage guest idle = "images/nova.png"\n',
        encoding="utf-8",
    )
    profile = tmp_path / "profile.json"
    profile.write_text(
        '{"character_selection":"manual","character_tags":["guest"]}',
        encoding="utf-8",
    )

    discovery = discover_project(project, profile)

    assert list(discovery.sprites) == ["guest idle"]


def test_scan_exposes_non_selected_story_families_for_manual_review(tmp_path: Path) -> None:
    project = make_project(tmp_path / "project")
    game = project / "game"
    sticker = Image.new("RGBA", (122, 173), (0, 0, 0, 0))
    sticker.save(game / "images" / "sticker.png")
    script = game / "script.rpy"
    script.write_text(
        script.read_text(encoding="utf-8")
        + '\nimage poem_sticker happy = "images/sticker.png"\n'
        + "show poem_sticker happy\n",
        encoding="utf-8",
    )

    discovery = discover_project(project)

    assert "poem_sticker" not in discovery.character_tags
    assert discovery.character_candidates["poem_sticker"].endswith("sticker.png")
