"""Lossless, indexed lighting frames, readable by Python 2 Ren'Py hosts.

The reader retains at most two decoded frames. Entries contain the exact shader
input bytes, including the live transport metadata row; no interpolation occurs.
"""

from __future__ import division

import collections
import json
import zipfile

VERSION = 2
FIELDS = (("irradiance", 160, 90), ("emitter", 160, 90), ("wrap", 160, 90), ("transport", 416, 10))
FRAME_BYTES = sum(width * height * 4 for _, width, height in FIELDS)


class Reader(object):
    def __init__(self, source, expected=None):
        self.source = source if hasattr(source, "read") else None
        self.archive = None
        self.frames = collections.OrderedDict()
        self.signatures = {}
        try:
            self.archive = zipfile.ZipFile(source, "r")
            info = self.archive.getinfo("manifest.json")
            if info.file_size > 64 * 1024 * 1024:
                raise ValueError("Lighting manifest is too large")
            self.metadata = json.loads(self.archive.read(info).decode("utf-8"))
            if self.metadata.get("version") != VERSION:
                raise ValueError("Unsupported prepared lighting version")
            self.count = int(self.metadata["frame_count"])
            if self.count < 1 or self.count > len(self.archive.infolist()) - 1:
                raise ValueError("Empty prepared lighting")
            for key, value in (expected or {}).items():
                if self.metadata.get(key) != value:
                    raise ValueError("Prepared lighting mismatch: " + key)
            for index in range(self.count):
                if self.archive.getinfo("frames/%d" % index).file_size != FRAME_BYTES:
                    raise ValueError("Invalid prepared frame size")
            signatures = self.metadata.get("frame_signatures", [])
            hashes = self.metadata.get("field_hashes", [])
            if signatures and (len(signatures) != self.count or len(hashes) != self.count):
                raise ValueError("Incomplete decoded frame index")
            for index, signature in enumerate(signatures):
                if signature in self.signatures:
                    previous = self.signatures[signature]
                    if previous is None or hashes[previous] != hashes[index]:
                        self.signatures[signature] = None
                else:
                    self.signatures[signature] = index
        except Exception:
            self.close()
            raise

    def frame(self, index):
        index = int(index)
        if index < 0 or index >= self.count:
            raise IndexError(index)
        if index in self.frames:
            value = self.frames.pop(index)
        else:
            raw = self.archive.read("frames/%d" % index)
            if len(raw) != FRAME_BYTES:
                raise ValueError("Truncated prepared lighting frame")
            value, offset = {}, 0
            for name, width, height in FIELDS:
                end = offset + width * height * 4
                value[name] = raw[offset:end]
                offset = end
        self.frames[index] = value
        while len(self.frames) > 2:
            self.frames.popitem(last=False)
        return value

    def close(self):
        self.frames.clear()
        self.signatures.clear()
        if self.archive is not None:
            self.archive.close()
        if self.source is not None:
            self.source.close()
