"""Compare Ren'Py RPC2 scripts without loading their Python objects."""

import hashlib
import pickletools
import struct
import zlib
from pathlib import Path
from typing import NamedTuple


class _Integer(NamedTuple):
    value: int
    offset: int
    end: int


class _Global(str):
    pass


class _Instance(NamedTuple):
    kind: str


_LIMIT = 24 * 1024 * 1024
_UNKNOWN = object()
_INT_SIZES = {"BININT": 5, "BININT1": 2, "BININT2": 3}
_STATE_KEYS = {"name", "filename", "serial", "location"}
_SCREEN_NODES = {
    "renpy.sl2.slast " + name
    for name in "SLBlock SLDisplayable SLIf SLShowIf SLFor SLBreak SLContinue SLPython SLPass SLDefault SLUse SLTransclude SLCustomUse SLScreen".split()
}
_NODE_TYPES = frozenset(
    "Call Camera Default Define EarlyPython Hide If Image Init Jump Label Menu Pass Python "
    "Return RPY Say Scene Screen Show ShowLayer Style Testcase Transform Translate TranslateBlock "
    "TranslateEarlyBlock TranslatePython TranslateSay EndTranslate UserStatement While With".split()
)


def _compiler_fields(target, state):
    """Locate the identifiers Ren'Py assigns when compiling AST and screen nodes."""
    if not isinstance(target, _Instance):
        return ()
    if target.kind in _SCREEN_NODES and isinstance(state, dict):
        loc, serial = state.get("location"), state.get("serial")
        if (
            type(loc) is tuple
            and len(loc) == 2
            and isinstance(loc[0], str)
            and isinstance(loc[1], _Integer)
            and isinstance(serial, _Integer)
        ):
            return state, (serial,)
    if type(state) is not tuple:
        return ()
    if target.kind == "renpy.ast PyCode" and len(state) in (4, 5):
        loc = state[2]
        if (
            isinstance(state[0], _Integer)
            and state[0].value == 1
            and state[3] in ("exec", "eval", "hide")
            and type(loc) is tuple
            and len(loc) in (3, 4)
            and isinstance(loc[0], str)
            and isinstance(loc[1], _Integer)
            and isinstance(loc[-1], _Integer)
        ):
            return loc, (loc[-1],)
    if target.kind.startswith("renpy.ast ") and target.kind[10:] in _NODE_TYPES:
        if len(state) == 2 and state[0] is None and isinstance(state[1], dict):
            name = state[1].get("name")
            if (
                type(name) is tuple
                and len(name) == 3
                and isinstance(name[0], str)
                and name[0] == state[1].get("filename")
                and all(isinstance(i, _Integer) for i in name[1:])
            ):
                return name, name[1:]
    return ()


def _pickle_digest(data):
    # Track operand types and offsets. GLOBAL, REDUCE and NEWOBJ never invoke game code.
    if not data.startswith(b"\x80\x02"):
        return None
    stack, marks, memo = [], [], {}
    replacements, referenced = {}, set()
    owners, screen_ids, statement_ids = [], {}, {}
    for count, (op, arg, pos) in enumerate(pickletools.genops(data)):
        if count > 3_000_000 or len(marks) > 2048:
            return None
        code = op.name
        if code in _INT_SIZES:
            stack.append(_Integer(arg, pos, pos + _INT_SIZES[code]))
        elif code == "LONG1":
            stack.append(_Integer(arg, pos, pos + 2 + data[pos + 1]))
        elif code in ("BINUNICODE", "SHORT_BINSTRING", "BINSTRING", "UNICODE"):
            stack.append(arg)
        elif code in ("NONE", "EMPTY_DICT", "EMPTY_TUPLE"):
            stack.append({} if code == "EMPTY_DICT" else () if code == "EMPTY_TUPLE" else None)
        elif code in ("EMPTY_LIST", "NEWFALSE", "NEWTRUE", "BINFLOAT", "LONG4"):
            stack.append(_UNKNOWN)
        elif code == "GLOBAL":
            stack.append(_Global(arg))
        elif code in ("BINPUT", "LONG_BINPUT"):
            memo[arg] = stack[-1]
        elif code in ("BINGET", "LONG_BINGET"):
            value = memo[arg]
            if type(value) in (tuple, dict) or isinstance(value, _Integer):
                referenced.add(id(value))
            stack.append(value)
        elif code == "MARK":
            marks.append(stack)
            stack = []
        elif code in ("TUPLE", "SETITEMS", "APPENDS"):
            items, stack = stack, marks.pop()
            if code == "TUPLE":
                stack.append(tuple(items))
            elif code == "SETITEMS" and isinstance(stack[-1], dict):
                for key, value in zip(items[::2], items[1::2]):
                    if type(key) is str and key in _STATE_KEYS:
                        stack[-1][key] = value
        elif code in ("TUPLE1", "TUPLE2", "TUPLE3"):
            size = int(code[-1])
            if len(stack) < size:
                return None
            items = tuple(stack[-size:])
            del stack[-size:]
            stack.append(items)
        elif code == "SETITEM":
            value, key = stack.pop(), stack.pop()
            if isinstance(stack[-1], dict) and type(key) is str and key in _STATE_KEYS:
                stack[-1][key] = value
        elif code in ("NEWOBJ", "REDUCE"):
            stack.pop()
            parent = stack.pop()
            stack.append(
                _Instance(parent) if code == "NEWOBJ" and isinstance(parent, _Global) else _UNKNOWN
            )
        elif code == "BUILD":
            state = stack.pop()
            fields = _compiler_fields(stack[-1], state)
            if fields:
                owner, integers = fields
                owners.append((owner, integers))
                identity = 0
                if stack[-1].kind in _SCREEN_NODES:
                    identity = screen_ids.setdefault(integers[0].value, len(screen_ids))
                elif len(integers) == 2:
                    key = (owner[0], integers[0].value, integers[1].value)
                    identity = statement_ids.setdefault(key, len(statement_ids))
                for number in integers:
                    replacements[number.offset] = (number.end, identity)
        elif code == "APPEND":
            stack.pop()
        elif code == "STOP":
            if pos + 1 != len(data) or len(stack) != 1 or marks:
                return None
        elif code != "PROTO" or arg != 2:
            return None
    # A value referenced elsewhere may be game data as well as compiler metadata.
    if any(
        id(owner) in referenced or any(id(n) in referenced for n in nums) for owner, nums in owners
    ):
        return None
    digest = hashlib.sha256()
    view = memoryview(data)
    start = 0
    for offset, (end, identity) in sorted(replacements.items()):
        digest.update(view[start:offset])
        digest.update(b"J" + struct.pack("<i", identity))
        start = end
    digest.update(view[start:])
    return digest.digest()


def compiled_fingerprint(path: Path) -> str | None:
    """Hash both compiled slots; unsupported formats keep using the exact file hash."""
    try:
        size_on_disk = path.stat().st_size
        if size_on_disk > _LIMIT:
            return None
        with path.open("rb") as stream:
            header = stream.read(46)
            if len(header) != 46 or header[:10] != b"RENPY RPC2" or header[34:] != bytes(12):
                return None
            digest, slots = hashlib.sha256(), {}
            previous_end = len(header)
            for index in range(2):
                slot, start, size = struct.unpack_from("<III", header, 10 + 12 * index)
                if (
                    slot != index + 1
                    or start < previous_end
                    or start + size > size_on_disk - 16
                    or not size
                ):
                    return None
                previous_end = start + size
                stream.seek(start)
                packed = stream.read(size)
                key = hashlib.sha256(packed).digest()
                if key not in slots:
                    decoder = zlib.decompressobj()
                    raw = decoder.decompress(packed, _LIMIT + 1)
                    if len(raw) > _LIMIT or not decoder.eof or decoder.unused_data:
                        return None
                    result = _pickle_digest(raw)
                    if result is None:
                        return None
                    slots[key] = result
                digest.update(slots[key])
            return digest.hexdigest()
    except (
        OSError,
        ValueError,
        IndexError,
        KeyError,
        TypeError,
        OverflowError,
        struct.error,
        zlib.error,
    ):
        return None
