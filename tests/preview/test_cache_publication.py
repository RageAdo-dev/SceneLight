import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from scenelight.preview import artifacts


def test_identical_form_requests_wait_for_complete_publication(tmp_path, monkeypatch):
    source = tmp_path / "sprite.png"
    Image.new("RGBA", (64, 96), (40, 80, 120, 255)).save(source)
    cache = artifacts.ArtifactCache(tmp_path / "cache")
    entered, release = threading.Event(), threading.Event()
    original = artifacts.build_sprite_form_maps
    calls = []

    def build(sprite):
        calls.append(True)
        entered.set()
        assert release.wait(3)
        return original(sprite)

    monkeypatch.setattr(artifacts, "build_sprite_form_maps", build)
    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(cache.form, source)
        assert entered.wait(2)
        others = [executor.submit(cache.form, source) for _ in range(2)]
        try:
            assert not any(future.done() for future in others)
        finally:
            release.set()
        results = [first.result(), *(future.result() for future in others)]
    assert len(calls) == 1
    assert sum(result.cached for result in results) == 2
    for result in results:
        for name in ("normal_noise", "height_ao_edge", "response"):
            with Image.open(result.image(name)) as image:
                image.load()
    assert len({result.root for result in results}) == 1
