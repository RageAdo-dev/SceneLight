"""Interrupted captures retain usable batches without trusting damaged output."""

import json

import pytest
from PIL import Image

import scenelight.capture as capture
from scenelight.project import ProjectDiscovery


def test_parallel_restart_keeps_completed_shards_when_worker_count_changes(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "project"
    (root / "game").mkdir(parents=True)
    discovery = ProjectDiscovery(root, root / "game", {}, {}, [])
    cache = root / ".scenelight_cache"
    cache.mkdir()
    workers = [2]
    attempts = []
    interrupted = [True]
    monkeypatch.setattr(capture, "_capture_form_worker_count", lambda _count: workers[0])
    monkeypatch.setattr(capture, "_capture_worker_renderers", lambda *_args: [None])
    monkeypatch.setattr(capture, "_schedule_capture_worker_cleanup", lambda _path: None)

    def run_worker(item, _executable, *, request_path, result_path, capture_root, **_kwargs):
        forms = json.loads(request_path.read_text())["explicit_forms"]
        attempts.append((item.project_root.name, tuple(forms)))
        sprites = {}
        for index, name in enumerate(forms):
            image = capture_root / (name.replace(" ", "_") + ".png")
            if image.is_file():
                assert image.read_bytes() == saved_pixels[image]
            else:
                Image.new("RGBA", (32, 32), (80, 120, 180, 128)).save(image)
                if item.project_root.name == "w2":
                    image.with_name(image.name + ".surface-checkpoint").write_text("raw")
            sprites[name] = str(image)
            with (capture_root / "capture_forms.jsonl").open("a") as journal:
                journal.write(json.dumps({"name": name, "relative": str(image)}) + "\n")
            if item.project_root.name == "w2" and interrupted[0] and index == 0:
                saved_pixels[image] = image.read_bytes()
                raise RuntimeError("device unavailable")
        result_path.write_text(
            json.dumps(
                {
                    "version": capture.CAPTURE_VERSION,
                    "sprites": sprites,
                    "surface_captures": list(sprites.values()),
                }
            )
        )

    saved_pixels = {}
    monkeypatch.setattr(capture, "_run_capture_request_resumable", run_worker)

    def run():
        return capture._run_parallel_capture_workers(
            discovery,
            tmp_path / "sdk.exe",
            cache_root=cache,
            capture_root=cache / "captured",
            planned_forms=["a one", "a two", "b one", "b two"],
            master_payload={},
            native_runtime=False,
            timeout_seconds=10,
            renderer=None,
        )

    with pytest.raises(RuntimeError, match="device unavailable"):
        run()
    first = dict(attempts)
    capsys.readouterr()
    workers[0] = 1
    interrupted[0] = False
    attempts.clear()
    result = run()
    assert attempts == [("w2", first["w2"])]
    assert sum(len(payload["sprites"]) for payload in result) == 4
    assert "parallel forms 3/4" in capsys.readouterr().out
    attempts.clear()
    cached = run()
    assert [row["sprites"] for row in cached] == [row["sprites"] for row in result]
    assert [row["surface_captures"] for row in cached] == [
        row["surface_captures"] for row in result
    ]
    assert attempts == []


def test_saved_worker_reclassifies_normalized_pixels_and_rejects_missing_markers(tmp_path):
    image = tmp_path / "sprite.png"
    Image.new("RGBA", (16, 16), (100, 200, 50, 128)).save(image)
    result = tmp_path / "worker-complete.json"
    payload = {
        "version": capture.CAPTURE_VERSION,
        "sprites": {"hero": "sprite.png"},
        "surface_captures": ["sprite.png"],
    }
    result.write_text(json.dumps({"version": 1, "forms": ["hero"], "payload": payload}))
    assert capture._saved_worker_result(tmp_path, result, ["hero"]) is None
    marker = image.with_name(image.name + ".surface-normalized")
    marker.write_text("normalized")
    before = image.read_bytes()
    restored = capture._saved_worker_result(tmp_path, result, ["hero"])
    assert restored["surface_captures"] == []
    assert restored["normalized_captures"] == ["sprite.png"]
    capture._normalize_surface_captures(tmp_path, restored)
    assert image.read_bytes() == before
    assert capture._saved_worker_result(tmp_path, result, ["different"]) is None
    image.unlink()
    assert capture._saved_worker_result(tmp_path, result, ["hero"]) is None
    result.write_text('{"unfinished":')
    assert capture._saved_worker_result(tmp_path, result, ["hero"]) is None


def test_saved_capture_plan_changes_only_for_a_changed_form_list(tmp_path):
    forms = ["a one", "a two", "b one", "b two"]
    first = capture._saved_capture_chunks(tmp_path, forms, 2)
    assert len(first) == 2
    assert capture._saved_capture_chunks(tmp_path, forms, 1) == first
    changed = forms + ["c one"]
    assert capture._saved_capture_chunks(tmp_path, changed, 1) == [changed]


@pytest.mark.parametrize("crash", [False, True])
def test_clean_batches_do_not_consume_the_crash_retry_budget(tmp_path, monkeypatch, crash):
    (tmp_path / "game").mkdir()
    discovery = ProjectDiscovery(tmp_path, tmp_path / "game", {}, {}, [])
    calls = []
    clean_batches = capture.CAPTURE_PROCESS_RESUME_LIMIT + 3
    monkeypatch.setattr(capture, "CAPTURE_LOW_YIELD_CRASH_LIMIT", 100)

    def batch(*_args, **kwargs):
        calls.append(kwargs["progress_state"])
        if len(calls) > clean_batches:
            return True
        (tmp_path / f"sprite_{len(calls)}.png.surface-checkpoint").write_text("raw")
        if crash:
            raise RuntimeError("renderer stopped (exit 1)")
        return False

    monkeypatch.setattr(capture, "_run_capture_request", batch)

    def run():
        capture._run_capture_request_resumable(
            discovery,
            tmp_path / "sdk.exe",
            request_path=tmp_path / "request.json",
            result_path=tmp_path / "result.json",
            native_runtime=False,
            timeout_seconds=5,
            purpose="capture",
            progress_path=tmp_path / "progress.json",
            composite_job_root=tmp_path / "composites",
            renderer=None,
            capture_root=tmp_path,
        )

    if crash:
        with pytest.raises(RuntimeError, match="exit 1"):
            run()
        assert len(calls) == capture.CAPTURE_PROCESS_RESUME_LIMIT + 1
    else:
        run()
        assert len(calls) == clean_batches + 1
    assert all(state is calls[0] for state in calls)


def test_partial_composite_progress_uses_published_journal_and_existing_layers(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    layer = tmp_path / "layer.png"
    Image.new("RGBA", (16, 16), "red").save(layer)
    destination = worker / "composite.png"
    (worker / "capture_forms.jsonl").write_text(
        json.dumps(
            {
                "name": "hero layered",
                "relative": str(destination),
            }
        )
        + "\n"
    )
    manifest = {"size": [16, 16], "layers": [{"source": str(layer), "position": [0, 0]}]}
    (worker / "composite_manifest.jsonl").write_text(
        json.dumps(
            {
                "destination": str(destination),
                "manifest": manifest,
            }
        )
        + '\n{"interrupted":'
    )
    assert capture._saved_worker_progress(tmp_path, worker, ["hero layered"]) == 1
    assert capture._saved_worker_progress(tmp_path, worker, ["other"]) == 0
    layer.unlink()
    assert capture._saved_worker_progress(tmp_path, worker, ["hero layered"]) == 0
