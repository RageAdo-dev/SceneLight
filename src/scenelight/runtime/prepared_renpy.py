"""Conservative movie cache binding, outside Ren'Py's save/rollback store."""

from __future__ import division

import collections
import hashlib
import json


class Movies(object):
    def __init__(self, api, reader):
        self.api, self.reader = api, reader
        self.opened = collections.OrderedDict()
        self.failed = set()
        self.decoded = {}
        with api.file("scenelight_runtime/prepared_movies.json") as stream:
            self.entries = json.load(stream)
        digest = hashlib.sha256(b"scenelight-prepared-v3")
        for name in ("live_gpu", "live_opencl"):
            with api.file("scenelight_runtime/" + name + ".txt") as stream:
                digest.update(stream.read())
        self.engine = digest.hexdigest()

    def observe(self, channel, surface):
        """Identify the existing decode with a tiny nearest-neighbor pixel grid.

        Uniqueness is checked against every authored frame during preparation;
        ambiguous or decoder-different signatures retain live analysis.
        """
        self.decoded.pop(channel.name, None)
        try:
            source = self.api.music.get_playing(channel=channel.name)
            if source not in self.entries:
                return
            width, height = surface.get_size()
            raw = bytearray()
            for y in range(9):
                for x in range(16):
                    raw.extend(surface.get_at((x * width // 16, y * height // 9)))
            self.decoded[channel.name] = (source, hashlib.sha256(raw).hexdigest())
        except Exception:
            # An alternate decoder need not expose an SDL surface.
            pass

    def install_decode_hook(self):
        channel = self.api.audio.audio.Channel
        current = channel.read_video
        original = getattr(current, "_scenelight_decode_original", current)

        def read_video(instance, *args, **kwargs):
            surface = original(instance, *args, **kwargs)
            if surface is not None:
                self.observe(instance, surface)
            return surface

        read_video._scenelight_decode_original = original
        channel.read_video = read_video

    def frame(self, background, rendered, width, height):
        api = self.api
        # Unwrap image references and neutral engine placement transforms only.
        # Any authored visual transform must analyze its rendered appearance.
        child = background.child
        seen = set()
        transform = api.display.transform
        while id(child) not in seen and len(seen) < 64:
            seen.add(id(child))
            if type(child) is api.display.image.ImageReference:
                if child.target is None:
                    child.find_target()
                child = child.target
            elif type(child) is transform.Transform and child.function is None:
                defaults = transform.TransformState()
                for name in transform.all_properties:
                    if name not in (
                        "xpos",
                        "ypos",
                        "xanchor",
                        "yanchor",
                        "xanchoraround",
                        "yanchoraround",
                    ):
                        if getattr(child.state, name) != getattr(defaults, name):
                            return None
                child = child.child
            else:
                break
        if not isinstance(child, api.display.video.Movie):
            return None
        if getattr(child, "mask", None) or getattr(child, "side_mask", False):
            return None
        if rendered.get_size() != (width, height):
            return None
        channel = child.channel
        shown = getattr(api.display, "_scenelight_presented_movies", {}).get(channel)
        if shown is None or shown[2] is not api.display.video.texture.get(channel):
            return None
        source, position, texture = shown[:3]
        signature = shown[3] if len(shown) > 3 else None
        if source != api.music.get_playing(channel=channel) or signature is None:
            return None
        entry = self.entries.get(source)
        if entry is None or source in self.failed or entry.get("size") != [width, height]:
            return None
        try:
            cached = self.opened.pop(source, None)
            if cached is None:
                digest = hashlib.sha256()
                with api.file(source) as stream:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                cached = self.reader(
                    api.file(entry["cache"]),
                    {
                        "engine": self.engine,
                        "source": digest.hexdigest(),
                        "preview": False,
                    },
                )
            self.opened[source] = cached
            while len(self.opened) > 2:
                self.opened.popitem(last=False)[1].close()
            index = cached.signatures.get(signature)
            if index is None:
                return None
            return (texture, index), cached.frame(index)
        except Exception:
            self.failed.add(source)
            api.display.log.write("SceneLight prepared movie unavailable: " + source)
            return None
