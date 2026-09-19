import ast
import json
import textwrap

import pytest
from PIL import Image

from scenelight.calibration import Calibration
from scenelight.preview.library import (
    Actor,
    Layer,
    Library,
    author_rules,
    compose_layers,
    load_scene,
    save_scene,
)


def test_layer_order_offsets_visibility_and_opacity(tmp_path):
    red = tmp_path / "red.png"
    blue = tmp_path / "blue.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(red)
    Image.new("RGBA", (5, 5), (0, 0, 255, 255)).save(blue)
    result = compose_layers([Layer(str(red)), Layer(str(blue), 5, 5, 0.5)], (20, 20))
    assert result.getpixel((6, 6)) == (127, 0, 128, 255)
    assert result.getpixel((2, 2)) == (255, 0, 0, 255)
    assert result.getpixel((18, 18)) == (0, 0, 0, 0)
    hidden = compose_layers([Layer(str(red)), Layer(str(blue), visible=False)])
    assert hidden.getpixel((2, 2)) == (255, 0, 0, 255)
    with pytest.raises(ValueError, match="canvas"):
        compose_layers([Layer(str(red))], (99999, 99999))


def test_saved_library_copies_media_recipes_and_individual_settings(tmp_path):
    source = tmp_path / "hero.png"
    Image.new("RGBA", (8, 8), (120, 90, 60, 255)).save(source)
    library = Library(tmp_path / "library")
    actor = Actor(
        name="Hero", source=str(source), strength=0.42, calibration=Calibration(glow_color_mix=0.3)
    )
    entry = library.add(
        "sprite", source, actor=actor, layers=[Layer(str(source), 1, 2)], canvas=(10, 10)
    )
    source.unlink()
    loaded = Library(library.root).entries()[0]
    assert library.path(loaded["source"]).is_file()
    assert library.path(loaded["layers"][0]["path"]).is_file()
    assert loaded["layers"][0]["name"] == "hero.png"
    assert library.path(loaded["thumbnail"]).is_file()
    restored = Actor.from_payload(loaded["actor"])
    assert restored.strength == 0.42 and restored.calibration.glow_color_mix == 0.3
    library.remove(entry["id"])
    assert library.entries() == []
    assert library.path(loaded["source"]).is_file()
    with pytest.raises(ValueError, match="outside"):
        library.path("../missing.png")


def test_scene_roundtrip_and_exported_rules_keep_characters_independent(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    for path in (first, second):
        Image.new("RGBA", (2, 2), "white").save(path)
    actors = [
        Actor(
            name="First",
            source=str(first),
            image_name="hero happy",
            strength=0.3,
            calibration=Calibration(glow_color_mix=0.35),
        ),
        Actor(
            name="Second",
            source=str(second),
            image_name="friend happy",
            strength=1.4,
            calibration=Calibration(exposure_bias=-0.8),
        ),
    ]
    destination = tmp_path / "scene.json"
    save_scene(destination, str(first), actors)
    background, restored = load_scene(destination)
    assert background == first
    assert [a.payload() for a in actors] == [a.payload() for a in restored]
    calls = []
    api = type("API", (), {"image": lambda self, name, **values: calls.append((name, values))})()
    rules = author_rules(restored)
    body = rules.split("init python:\n", 1)[1]
    exec(compile(ast.parse(textwrap.dedent(body)), "rules", "exec"), {"scenelight": api})
    assert calls[0][1]["strength"] == 0.3
    assert calls[1][1]["strength"] == 1.4
    assert calls[0][1]["glow_color_mix"] == 0.35
    restored[1].image_name = restored[0].image_name
    with pytest.raises(ValueError, match="same image"):
        author_rules(restored)
    payload = json.loads(destination.read_text())
    payload["actors"][1]["id"] = payload["actors"][0]["id"]
    destination.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="duplicate"):
        load_scene(destination)


def test_scene_supports_assets_on_a_different_windows_drive(tmp_path, monkeypatch):
    import scenelight.preview.library as library

    source = tmp_path / "sprite.png"
    Image.new("RGBA", (2, 2), "white").save(source)
    monkeypatch.setattr(
        library.os.path,
        "relpath",
        lambda *args: (_ for _ in ()).throw(ValueError("different drive")),
    )
    scene = tmp_path / "scene.json"
    save_scene(scene, str(source), [Actor(source=str(source))])
    background, actors = load_scene(scene)
    assert background == source
    assert actors[0].source == str(source)
