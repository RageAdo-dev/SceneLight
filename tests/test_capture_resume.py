"""Interrupted captures retain usable batches without trusting damaged output."""

import json
from pathlib import Path

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


def _simulator(tmp_path: Path, forms: list[str], crashing: set[str]):
    """Fake the engine: honour skip_forms, save the good forms, die on the bad."""

    request = tmp_path / "request.json"
    request.write_text(json.dumps({"version": 42}), encoding="utf-8")

    def capture_request(*_args, **kwargs):
        payload = json.loads(request.read_text(encoding="utf-8"))
        skip = set(payload.get("skip_forms", []))
        pending = [
            name
            for name in forms
            if name not in skip
            and not (tmp_path / f"sprite_{name}.png.surface-checkpoint").is_file()
        ]
        for name in pending:
            if name in crashing:
                kwargs["progress_path"].write_text(
                    json.dumps(
                        {
                            "stage": "form.start",
                            "current": forms.index(name) + 1,
                            "total": len(forms),
                            "item": name,
                        }
                    ),
                    encoding="utf-8",
                )
                raise RuntimeError("Ren'Py could not inventory (exit 3221225477).")
            (tmp_path / f"sprite_{name}.png.surface-checkpoint").write_text("raw", encoding="utf-8")
        return True

    return request, capture_request


def _resume(tmp_path: Path, discovery: ProjectDiscovery) -> None:
    capture._run_capture_request_resumable(
        discovery,
        tmp_path / "sdk.exe",
        request_path=tmp_path / "request.json",
        result_path=tmp_path / "result.json",
        native_runtime=False,
        timeout_seconds=5,
        purpose="inventory",
        progress_path=tmp_path / "progress.json",
        composite_job_root=tmp_path / "composites",
        renderer=None,
        capture_root=tmp_path,
    )


def test_a_crashing_form_is_skipped_and_the_rest_finish(tmp_path, monkeypatch):
    (tmp_path / "game").mkdir()
    discovery = ProjectDiscovery(tmp_path, tmp_path / "game", {}, {}, [])
    forms = ["adam", "andres", "bruce"]
    request, capture_request = _simulator(tmp_path, forms, {"andres"})
    monkeypatch.setattr(capture, "_run_capture_request", capture_request)

    _resume(tmp_path, discovery)

    assert json.loads(request.read_text(encoding="utf-8"))["skip_forms"] == ["andres"]
    assert (tmp_path / "sprite_adam.png.surface-checkpoint").is_file()
    assert (tmp_path / "sprite_bruce.png.surface-checkpoint").is_file()
    assert not (tmp_path / "sprite_andres.png.surface-checkpoint").exists()


def test_every_crashing_form_is_recorded_once_and_the_run_completes(tmp_path, monkeypatch):
    (tmp_path / "game").mkdir()
    discovery = ProjectDiscovery(tmp_path, tmp_path / "game", {}, {}, [])
    forms = ["adam", "andres", "bruce", "yuri wings"]
    request, capture_request = _simulator(tmp_path, forms, set(forms))
    monkeypatch.setattr(capture, "_run_capture_request", capture_request)
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return capture_request(*args, **kwargs)

    monkeypatch.setattr(capture, "_run_capture_request", counted)

    _resume(tmp_path, discovery)

    assert sorted(json.loads(request.read_text(encoding="utf-8"))["skip_forms"]) == sorted(forms)
    assert len(calls) == len(forms) + 1


def test_a_crash_without_progress_still_stops_instead_of_spinning(tmp_path, monkeypatch):
    (tmp_path / "game").mkdir()
    discovery = ProjectDiscovery(tmp_path, tmp_path / "game", {}, {}, [])
    request, _capture_request = _simulator(tmp_path, ["adam"], {"adam"})

    def no_progress(*_args, **_kwargs):
        (tmp_path / "progress.json").write_text(
            json.dumps({"stage": "plan", "current": 1, "total": 2}), encoding="utf-8"
        )
        raise RuntimeError("Ren'Py could not inventory (exit 3221225477).")

    monkeypatch.setattr(capture, "_run_capture_request", no_progress)

    with pytest.raises(RuntimeError, match="exit 3221225477"):
        _resume(tmp_path, discovery)
    assert "skip_forms" not in json.loads(request.read_text(encoding="utf-8"))


def test_review_keeps_recorded_skips_for_the_next_renderer(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "game").mkdir(parents=True)
    discovery = ProjectDiscovery(project, project / "game", {}, {}, [])
    requests: list[dict] = []

    def stop(*_args, request_path, **_kwargs):
        requests.append(json.loads(request_path.read_text(encoding="utf-8")))
        raise RuntimeError("stopped for the test")

    monkeypatch.setattr(capture, "_run_capture_request_resumable", stop)

    with pytest.raises(RuntimeError):
        capture.capture_runtime_review(discovery, tmp_path / "renpy.exe")
    cache_dir = next((project / ".scenelight_cache" / "review").iterdir())
    request_path = cache_dir / "request.json"
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    payload["skip_forms"] = ["andres"]
    request_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError):
        capture.capture_runtime_review(discovery, tmp_path / "renpy-gl2.exe", renderer="gl2")

    assert requests[-1]["skip_forms"] == ["andres"]


def test_review_does_not_retry_sprites_with_the_software_renderer(tmp_path, monkeypatch):
    """Character capture needs a GPU, so a software pass can only fail again."""

    project = tmp_path / "proj"
    (project / "game").mkdir(parents=True)
    discovery = ProjectDiscovery(project, project / "game", {}, {}, [])
    calls: list[str | None] = []

    def fake_capture(*_args, renderer, request_path, result_path, **_kwargs):
        calls.append(renderer)
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        payload["skip_forms"] = ["andres"]
        result_path.write_text(
            json.dumps(
                {
                    "version": capture.CAPTURE_VERSION,
                    "sprites": {},
                    "errors": ["sprite andres: the renderer stopped while capturing this form"],
                }
            ),
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(capture, "_run_capture_request_resumable", fake_capture)
    monkeypatch.setattr(capture, "_paths_exist", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(capture, "_write_capture_result", lambda *_a, **_k: None)

    result = capture.capture_runtime_review(discovery, tmp_path / "renpy.exe", renderer=None)

    assert calls == [None]
    assert result.sprites == {}


def test_parallel_merge_keeps_worker_scene_captures() -> None:
    """Backgrounds captured inside a worker must survive the merge."""

    master = {
        "version": capture.CAPTURE_VERSION,
        "sprites": {},
        "errors": [],
        "scenes": {"bedroom": "previews/scene_bedroom.png"},
        "character_tags": [],
        "surface_captures": [],
        "normalized_captures": [],
    }
    worker = {
        "version": capture.CAPTURE_VERSION,
        "sprites": {"hero idle": "previews/sprite_a.png"},
        "scenes": {"corridor": "previews/scene_corridor.png"},
        "composite_captures": {},
        "surface_captures": [],
        "normalized_captures": [],
        "errors": [],
    }

    merged = capture._merge_parallel_capture_payloads(
        master, [worker], {"hero": ["hero idle"]}
    )

    assert merged["scenes"] == {
        "bedroom": "previews/scene_bedroom.png",
        "corridor": "previews/scene_corridor.png",
    }


def test_parallel_merge_keeps_old_engine_capture_pairs() -> None:
    """A worker on an engine without offscreen readback reports pairs, not files."""

    master = {
        "version": capture.CAPTURE_VERSION,
        "sprites": {},
        "errors": [],
        "character_tags": ["hero"],
        "surface_captures": [],
        "normalized_captures": [],
    }
    worker = {
        "version": capture.CAPTURE_VERSION,
        "sprites": {"hero idle": "previews/sprite_a.png"},
        "composite_captures": {},
        "surface_captures": [],
        "normalized_captures": [],
        "errors": [],
        "matting_captures": [
            {"relative": "previews/sprite_a.png", "size": [4, 4], "crop": [4, 4]},
            {"relative": "previews/sprite_gone.png", "size": [4, 4], "crop": [4, 4]},
        ],
    }

    merged = capture._merge_parallel_capture_payloads(master, [worker], {"hero": ["hero idle"]})

    assert merged["sprites"] == {"hero idle": "previews/sprite_a.png"}
    # The unrelated pair belongs to a form this run did not keep.
    assert [entry["relative"] for entry in merged["matting_captures"]] == ["previews/sprite_a.png"]


def test_reset_request_skips_gives_the_next_backend_a_clean_slate(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"version": 42, "skip_forms": ["andres", "yuri wings"]}), encoding="utf-8"
    )

    capture._reset_request_skips(request)

    assert "skip_forms" not in json.loads(request.read_text(encoding="utf-8"))


def test_crash_records_the_in_flight_form_so_the_next_run_skips_it(tmp_path):
    progress = tmp_path / "progress.json"
    progress.write_text(
        json.dumps({"stage": "form.start", "current": 7, "total": 98, "item": "Andres"}),
        encoding="utf-8",
    )
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"version": 42}), encoding="utf-8")

    assert capture._last_attempted_form(progress) == "Andres"
    assert capture._add_request_skip_form(request, "Andres") is True
    assert json.loads(request.read_text(encoding="utf-8"))["skip_forms"] == ["andres"]
    assert capture._add_request_skip_form(request, "andres") is False
    progress.write_text(json.dumps({"stage": "form", "current": 7}), encoding="utf-8")
    assert capture._last_attempted_form(progress) is None


def test_capture_trace_tail_keeps_the_last_steps_and_their_paths(tmp_path):
    (tmp_path / "capture_attempts.jsonl").write_text(
        "\n".join(
            (
                json.dumps({"stage": "attempt", "form": "hero a", "output": "previews/a.png"}),
                json.dumps({"stage": "resolved", "form": "hero a", "sources": ["images/a.png"]}),
                "{not json",
            )
        )
        + "\n"
    )

    lines = capture._capture_trace_tail(tmp_path, limit=2).splitlines()

    assert len(lines) == 2
    assert '"stage": "resolved"' in lines[0]
    assert "images/a.png" in lines[0]
    assert lines[1] == "{not json"
    assert capture._capture_trace_tail(None) == ""


def test_progress_names_the_form_that_is_still_rendering():
    key, line = capture._capture_progress_line(
        {"stage": "form.start", "current": 65, "total": 98, "item": "yuri 1 aw"}
    )

    assert key == ("form.start", 65, 98, "yuri 1 aw")
    assert line == "SceneLight resolver capturing form 65/98: yuri 1 aw"


def test_crash_inside_a_journaled_form_resumes_until_the_form_is_skipped(tmp_path, monkeypatch):
    (tmp_path / "game").mkdir()
    discovery = ProjectDiscovery(tmp_path, tmp_path / "game", {}, {}, [])
    calls = []

    def crash(*_args, **_kwargs):
        calls.append(len(calls) + 1)
        attempt = len(calls)
        if attempt == 1:
            for index in range(capture.CAPTURE_LOW_YIELD_FORM_THRESHOLD):
                (tmp_path / f"sprite_{index}.png.surface-checkpoint").write_text("raw")
            (tmp_path / "form_attempts.json").write_text(json.dumps({"yuri 1 aw": 1}))
            raise RuntimeError("Ren'Py could not inventory (exit 3221225477).")
        if attempt == 2:
            (
                tmp_path
                / f"sprite_{capture.CAPTURE_LOW_YIELD_FORM_THRESHOLD}.png.surface-checkpoint"
            ).write_text("raw")
            (tmp_path / "form_attempts.json").write_text(json.dumps({"yuri 1 aw": 2}))
            raise RuntimeError("Ren'Py could not inventory (exit 3221225477).")
        # The third process skips the journaled form and finishes.
        (tmp_path / "form_attempts.json").write_text("{}")
        return True

    monkeypatch.setattr(capture, "_run_capture_request", crash)
    capture._run_capture_request_resumable(
        discovery,
        tmp_path / "sdk.exe",
        request_path=tmp_path / "request.json",
        result_path=tmp_path / "result.json",
        native_runtime=False,
        timeout_seconds=5,
        purpose="inventory",
        progress_path=tmp_path / "progress.json",
        composite_job_root=tmp_path / "composites",
        renderer=None,
        capture_root=tmp_path,
    )

    assert len(calls) == 3


def test_crash_without_saved_forms_or_a_journaled_form_fails_immediately(tmp_path, monkeypatch):
    (tmp_path / "game").mkdir()
    discovery = ProjectDiscovery(tmp_path, tmp_path / "game", {}, {}, [])
    calls = []

    def crash(*_args, **_kwargs):
        calls.append(1)
        raise RuntimeError("Ren'Py could not inventory (exit 3221225477).")

    monkeypatch.setattr(capture, "_run_capture_request", crash)
    with pytest.raises(RuntimeError, match="exit 3221225477"):
        capture._run_capture_request_resumable(
            discovery,
            tmp_path / "sdk.exe",
            request_path=tmp_path / "request.json",
            result_path=tmp_path / "result.json",
            native_runtime=False,
            timeout_seconds=5,
            purpose="inventory",
            progress_path=tmp_path / "progress.json",
            composite_job_root=tmp_path / "composites",
            renderer=None,
            capture_root=tmp_path,
        )

    assert len(calls) == 1
