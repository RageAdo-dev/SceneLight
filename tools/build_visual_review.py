"""Build a standalone, GPU-rendered SceneLight background review gallery."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

from scenelight.calibration import Calibration
from scenelight.preview.artifacts import ArtifactCache, SceneArtifacts
from scenelight.preview.gpu_view import SceneLightGPUView
from scenelight.preview.temporal import TemporalSceneFrame


def _rgba(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()


def _crop(array: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    left, top, right, bottom = box
    return np.ascontiguousarray(array[top:bottom, left:right])


def _save_webp(frame: np.ndarray, destination: Path) -> None:
    Image.fromarray(frame[..., :3], "RGB").save(
        destination,
        "WEBP",
        quality=88,
        method=4,
    )


def _category(metadata: dict[str, object]) -> str:
    adaptation = float(metadata.get("adaptation_luminance", 0.0))
    layout = str(metadata.get("light_transport_layout", ""))
    if adaptation < 0.055:
        return "low light"
    if layout == "physical-rgb-families-v1":
        return "separated color"
    return "ordinary"


def _html(records: list[dict[str, object]], benchmark: dict[str, object]) -> str:
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    performance = json.dumps(benchmark, ensure_ascii=False, separators=(",", ":"))
    collection_options = "".join(
        f'<option value="{html.escape(str(collection), quote=True)}">'
        f"{html.escape(str(collection))}</option>"
        for collection in dict.fromkeys(record["collection"] for record in records)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>SceneLight — all-background visual review</title>
<style>
:root {{ color-scheme: dark; --ink:#f3f7ff; --muted:#8ea1b8; --panel:#111a27;
  --line:#26364b; --cyan:#55d6ff; --pink:#ff78ba; --good:#72e0a6; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#070b11; color:var(--ink); font:15px/1.45 Inter,Segoe UI,sans-serif; }}
button,input,select {{ font:inherit; }}
.shell {{ width:min(1500px,100%); margin:auto; padding:24px; }}
header {{ display:flex; gap:24px; align-items:end; justify-content:space-between; margin-bottom:18px; }}
h1 {{ font-size:clamp(26px,4vw,48px); line-height:1; margin:0 0 9px; letter-spacing:-.04em; }}
.sub {{ color:var(--muted); max-width:760px; }}
.perf {{ display:grid; grid-template-columns:repeat(3,auto); border:1px solid var(--line); border-radius:14px;
  overflow:hidden; background:var(--panel); flex:none; }}
.perf div {{ padding:10px 16px; border-left:1px solid var(--line); }} .perf div:first-child {{ border:0; }}
.perf b {{ display:block; color:var(--cyan); font-size:20px; }} .perf span {{ color:var(--muted); font-size:12px; }}
.stage {{ position:relative; overflow:hidden; border:1px solid var(--line); border-radius:18px; background:#000;
  aspect-ratio:16/9; box-shadow:0 24px 80px #000a; }}
.stage img {{ position:absolute; inset:0; width:100%; height:100%; object-fit:contain; user-select:none; }}
#afterWrap {{ position:absolute; inset:0; overflow:hidden; width:50%; }}
#afterWrap img {{ width:calc(100vw - 48px); max-width:1452px; object-fit:contain; object-position:left top; }}
.wipe {{ position:absolute; z-index:3; top:0; bottom:0; left:50%; width:2px; background:#fff; box-shadow:0 0 0 1px #0008; }}
.wipe:after {{ content:'↔'; position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
  display:grid; place-items:center; width:38px; height:38px; border-radius:50%; background:#fff; color:#07101a; font-weight:900; }}
.tag {{ position:absolute; z-index:4; top:12px; padding:7px 10px; border-radius:8px; background:#07101ad9;
  backdrop-filter:blur(8px); font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
.tag.before {{ left:12px; }} .tag.after {{ right:12px; color:var(--good); }}
#wipeInput {{ position:absolute; z-index:5; inset:0; width:100%; height:100%; opacity:0; cursor:ew-resize; }}
.controls {{ display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:12px; align-items:center; padding:16px 0 12px; }}
.controls button {{ border:1px solid var(--line); background:var(--panel); color:var(--ink); border-radius:10px; padding:10px 16px; cursor:pointer; }}
.controls button:hover {{ border-color:var(--cyan); }}
#sceneInput {{ width:100%; accent-color:var(--cyan); }}
.meta {{ display:flex; flex-wrap:wrap; align-items:center; gap:9px; min-height:38px; }}
.meta h2 {{ margin:0 8px 0 0; font-size:21px; }} .chip {{ color:#b9c8d9; background:#111a27; border:1px solid var(--line);
  border-radius:999px; padding:5px 9px; font-size:12px; }}
.toolbar {{ margin:18px 0 10px; display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
.toolbar input,.toolbar select {{ color:var(--ink); background:var(--panel); border:1px solid var(--line); border-radius:9px; padding:9px 11px; }}
.toolbar input {{ flex:1 1 190px; min-width:0; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:10px; margin-top:14px; }}
.card {{ border:1px solid var(--line); background:var(--panel); color:var(--ink); padding:0; border-radius:11px; overflow:hidden; text-align:left; cursor:pointer; }}
.card:hover,.card.active {{ border-color:var(--cyan); }} .card img {{ display:block; width:100%; aspect-ratio:16/9; object-fit:cover; }}
.card span {{ display:block; padding:8px 10px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.count {{ color:var(--muted); margin-left:auto; }}
@media (max-width:850px) {{ header {{ display:block; }} .perf {{ margin-top:16px; grid-template-columns:repeat(3,1fr); }}
  .perf div {{ padding:9px; }} .shell {{ padding:12px; }} #afterWrap img {{ width:calc(100vw - 24px); }}
  .controls {{ gap:7px; }} .controls button {{ padding:9px 10px; }} .count {{ margin-left:0; }} }}
@media (prefers-reduced-motion:reduce) {{ * {{ scroll-behavior:auto!important; }} }}
</style>
</head>
<body><main class="shell">
<header><div><h1>All-background visual review</h1><div class="sub">Interaction and the custom reference-background set, rendered through SceneLight. Drag across the image to compare authored sprite color with the adaptive result.</div></div>
<div class="perf"><div><b id="beforeTime"></b><span>old 30 s video analysis</span></div><div><b id="afterTime"></b><span>new 30 s video analysis</span></div><div><b id="speedup"></b><span>cold speed-up</span></div></div></header>
<section class="stage" id="stage"><img id="before" alt="Original sprite"><div id="afterWrap"><img id="after" alt="SceneLight relit sprite"></div><div class="wipe" id="wipe"></div><span class="tag before">Original</span><span class="tag after">SceneLight</span><input id="wipeInput" aria-label="Before and after split" type="range" min="0" max="100" value="50"></section>
<div class="controls"><button id="prev">← Previous</button><input id="sceneInput" aria-label="Scene" type="range" min="0" max="0" value="0"><button id="next">Next →</button></div>
<div class="meta"><h2 id="sceneName"></h2><span class="chip" id="sceneNumber"></span><span class="chip" id="collection"></span><span class="chip" id="category"></span><span class="chip" id="lights"></span><span class="chip" id="luminance"></span></div>
<div class="toolbar"><input id="search" placeholder="Find a background…"><select id="collectionFilter"><option value="all">All collections</option>{collection_options}</select><select id="filter"><option value="all">All lighting</option><option value="ordinary">Ordinary</option><option value="low light">Low light</option><option value="separated color">Separated color</option><option value="reference">Reference tests</option></select><span class="count" id="count"></span></div>
<section class="grid" id="grid"></section>
</main>
<script>
const scenes={payload}, perf={performance};
const $=id=>document.getElementById(id); let visible=scenes.slice(), index=0;
function setWipe(v){{ $('afterWrap').style.width=v+'%'; $('wipe').style.left=v+'%'; }}
function show(i,scroll=false){{ if(!visible.length)return; index=(i+visible.length)%visible.length; const s=visible[index];
 $('before').src=s.original; $('after').src=s.relit; $('sceneName').textContent=s.name; $('sceneNumber').textContent=`${{index+1}} / ${{visible.length}}`;
 $('collection').textContent=s.collection; $('category').textContent=s.category;
 $('lights').textContent=s.lights==null?'reference render':`${{s.lights}} light${{s.lights===1?'':'s'}}`;
 $('luminance').textContent=s.adaptation==null?'custom scene':`adaptation ${{s.adaptation.toFixed(3)}}`; $('sceneInput').max=Math.max(0,visible.length-1); $('sceneInput').value=index;
 document.querySelectorAll('.card').forEach(c=>c.classList.toggle('active',c.dataset.name===s.name));
 [visible[(index+1)%visible.length],visible[(index-1+visible.length)%visible.length]].forEach(n=>{{new Image().src=n.relit;}});
 if(scroll)$('stage').scrollIntoView({{behavior:'smooth',block:'start'}});
}}
function rebuild(){{ const q=$('search').value.trim().toLowerCase(), f=$('filter').value, c=$('collectionFilter').value;
 visible=scenes.filter(s=>(f==='all'||s.category===f)&&(c==='all'||s.collection===c)&&s.name.toLowerCase().includes(q)); index=0; $('count').textContent=`${{visible.length}} scenes`;
 $('grid').innerHTML=visible.map(s=>`<button class="card" data-name="${{s.name}}"><img loading="lazy" src="${{s.relit}}" alt=""><span>${{s.name}}</span></button>`).join('');
 document.querySelectorAll('.card').forEach((c,i)=>c.onclick=()=>show(i,true)); show(0);
}}
$('wipeInput').oninput=e=>setWipe(e.target.value); $('sceneInput').oninput=e=>show(+e.target.value); $('prev').onclick=()=>show(index-1); $('next').onclick=()=>show(index+1);
$('search').oninput=rebuild; $('collectionFilter').onchange=rebuild; $('filter').onchange=rebuild; document.onkeydown=e=>{{ if(e.key==='ArrowLeft')show(index-1); if(e.key==='ArrowRight')show(index+1); }};
$('beforeTime').textContent=perf.before; $('afterTime').textContent=perf.after; $('speedup').textContent=perf.speedup; setWipe(50); rebuild();
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_result", type=Path)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("sprite", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--reference-pairs", type=Path)
    args = parser.parse_args()

    capture_path = args.capture_result.resolve(strict=True)
    project_root = capture_path.parents[1]
    runtime = args.runtime.resolve(strict=True)
    sprite = args.sprite.resolve(strict=True)
    output = args.output.resolve()
    images_root = output / "images"
    seed_root = output / ".seed-scene"
    images_root.mkdir(parents=True, exist_ok=True)
    seed_root.mkdir(parents=True, exist_ok=True)

    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    manifest = json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))
    captured = capture["scenes"]
    available = [name for name in manifest["scenes"] if name in captured]
    if args.limit is not None:
        available = available[: max(1, args.limit)]
    if not available:
        raise RuntimeError("No captured backgrounds match the SceneLight runtime manifest")

    irradiance_atlas = _rgba(runtime / "irradiance_atlas.png")
    emitter_atlas = _rgba(runtime / "emitter_atlas.png")
    wrap_atlas = _rgba(runtime / "wrap_atlas.png")
    transport_atlas = _rgba(runtime / "transport_atlas.png")
    tile_width, tile_height = manifest["atlas"]["tile_size"]
    grid_width, grid_height = manifest["transport_atlas"]["grid_size"]
    transport_width = grid_width * int(manifest["transport_atlas"]["planes"])

    def scene_arrays(name: str):
        metadata = manifest["scenes"][name]
        column, row = metadata["tile"]
        scene_box = (
            column * tile_width,
            row * tile_height,
            (column + 1) * tile_width,
            (row + 1) * tile_height,
        )
        transport_box = (
            column * transport_width,
            row * grid_height,
            (column + 1) * transport_width,
            (row + 1) * grid_height,
        )
        return (
            _crop(irradiance_atlas, scene_box),
            _crop(emitter_atlas, scene_box),
            _crop(wrap_atlas, scene_box),
            _crop(transport_atlas, transport_box),
            metadata,
        )

    first = available[0]
    seed_irradiance, seed_emitter, seed_wrap, seed_transport, seed_metadata = scene_arrays(first)
    for name, array in (
        ("irradiance", seed_irradiance),
        ("emitter", seed_emitter),
        ("wrap", seed_wrap),
        ("transport", seed_transport),
    ):
        Image.fromarray(array, "RGBA").save(seed_root / f"{name}.png")

    cache = ArtifactCache(output / ".preview-cache")
    form = cache.form(sprite)
    app = QApplication.instance() or QApplication(sys.argv)
    view = SceneLightGPUView()
    view.resize(1280, 720)
    view.show()
    app.processEvents()
    first_background = (project_root / captured[first]).resolve(strict=True)
    view.set_scene(first_background, SceneArtifacts(seed_root, seed_metadata, True, 0.0))
    view.set_sprite(sprite, form)
    view.set_placement(0.5, 1.03, 0.92)
    view.set_calibration(Calibration())
    app.processEvents()

    records: list[dict[str, object]] = []
    try:
        for item_index, scene_name in enumerate(available):
            background_path = (project_root / captured[scene_name]).resolve(strict=True)
            background = _rgba(background_path)
            irradiance, emitter, wrap, transport, metadata = scene_arrays(scene_name)
            view.set_background_frame(background, wrap)
            view.set_live_scene_frame(TemporalSceneFrame(irradiance, emitter, transport, metadata))
            app.processEvents()
            view.set_compare_mode(1)
            original = view.render_rgba((1280, 720))
            view.set_compare_mode(0)
            relit = view.render_rgba((1280, 720))
            slug = f"{item_index + 1:03d}"
            original_name = f"images/{slug}-original.webp"
            relit_name = f"images/{slug}-relit.webp"
            _save_webp(original, output / original_name)
            _save_webp(relit, output / relit_name)
            records.append(
                {
                    "name": scene_name,
                    "original": original_name,
                    "relit": relit_name,
                    "category": _category(metadata),
                    "collection": "Interaction",
                    "lights": int(metadata.get("lights", 0)),
                    "adaptation": float(metadata.get("adaptation_luminance", 0.0)),
                    "layout": str(metadata.get("light_transport_layout", "unknown")),
                }
            )
            if (item_index + 1) % 12 == 0 or item_index + 1 == len(available):
                print(f"rendered {item_index + 1}/{len(available)}", flush=True)
    finally:
        view.close()
        cache.shutdown()

    if args.reference_pairs is not None:
        reference_root = args.reference_pairs.resolve(strict=True)
        before_by_name = {
            path.stem.removesuffix("_before"): path for path in reference_root.glob("*_before.jpg")
        }
        after_by_name = {
            path.stem.removesuffix("_after"): path for path in reference_root.glob("*_after.jpg")
        }
        for reference_name in sorted(before_by_name.keys() & after_by_name.keys()):
            slug = f"{len(records) + 1:03d}"
            original_name = f"images/{slug}-original.webp"
            relit_name = f"images/{slug}-relit.webp"
            with Image.open(before_by_name[reference_name]) as image:
                _save_webp(
                    np.asarray(image.convert("RGBA"), dtype=np.uint8), output / original_name
                )
            with Image.open(after_by_name[reference_name]) as image:
                _save_webp(np.asarray(image.convert("RGBA"), dtype=np.uint8), output / relit_name)
            records.append(
                {
                    "name": reference_name.replace("_", " "),
                    "original": original_name,
                    "relit": relit_name,
                    "category": "reference",
                    "collection": "Reference backgrounds",
                    "lights": None,
                    "adaptation": None,
                    "layout": "reference-comparison",
                }
            )

    benchmark = {"before": "4m 58s", "after": "22s", "speedup": "13.5×"}
    (output / "index.html").write_text(_html(records, benchmark), encoding="utf-8")
    (output / "scenes.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(output / "index.html")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("QT_OPENGL", "desktop")
    raise SystemExit(main())
