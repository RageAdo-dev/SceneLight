"""Mask OS account names in diagnostic text, including older logs from another PC."""

import json
import os
import re
import sys

try:
    _text = unicode
    _strings = (basestring,)
except NameError:
    _text = str
    _strings = (str,)


def _native(value):
    if isinstance(value, _text):
        return value
    return value.decode(sys.getfilesystemencoding() or "utf-8", "replace")


_home = _native(os.path.expanduser("~"))
_homes = sorted(
    {_home, _home.replace("\\", "/"), _home.replace("\\", "\\\\")}, key=len, reverse=True
)
_homes = [v for v in _homes if len(v) > 1 and v != "~" and not v.endswith(("/", "\\"))]
_home_re = (
    re.compile("(?:" + "|".join(re.escape(v) for v in _homes) + r")(?=[\\/]|$|[\r\n\"'])", re.I)
    if _homes
    else None
)
_accounts = {_native(os.environ.get(k, "")) for k in ("USERNAME", "LOGNAME", "USER")}
if _homes:
    _accounts.add(re.split(r"[\\/]", _home)[-1])
_account_re = (
    re.compile(
        r"(?<![\w<])(?:"
        + "|".join(re.escape(v) for v in sorted(_accounts - {""}, key=len, reverse=True))
        + r")(?![\w>])",
        re.I | re.UNICODE,
    )
    if any(_accounts)
    else None
)
_profile = re.compile(
    r"""(?i)((?:[a-z]:[\\/]+|[\\/]+)(?:users|home|documents and settings)[\\/]+)(?!<USER>)([^\\/:"<>|\r\n]+)"""
)
_fields = {
    "user",
    "username",
    "logname",
    "accountname",
    "windowsusername",
    "fullname",
    "displayname",
}
_label = re.compile(
    r"(?im)(?<![\w])((?:user(?:[ _-]?name)?|logname|account[ _-]?name|windows user(?:name)?|full[ _-]?name|display[ _-]?name)[ \t]*[:=][ \t]*)[^\r\n]+"
)


def is_account_key(key):
    return isinstance(key, _strings) and re.sub(r"[^a-z0-9]", "", key.lower()) in _fields


def mask_text(text):
    text = _native(text)
    if text.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(text)
        except (ValueError, RuntimeError):
            if "\n" in text.rstrip("\r\n"):
                return "".join(
                    mask_text(line.rstrip("\r\n")) + line[len(line.rstrip("\r\n")) :]
                    for line in text.splitlines(True)
                )
        else:
            if isinstance(parsed, (dict, list)):
                masked = mask_value(parsed)
                return text if masked == parsed else json.dumps(masked, ensure_ascii=False)
    if _home_re:
        text = _home_re.sub("<USER>", text)
    text = _profile.sub(r"\g<1><USER>", text)
    if _account_re:
        text = _account_re.sub("<USER>", text)
    return _label.sub(r"\g<1><USER>", text)


def mask_value(value):
    if isinstance(value, dict):
        return {
            mask_text(k) if isinstance(k, _strings) else k: (
                "<USER>" if is_account_key(k) else mask_value(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [mask_value(v) for v in value]
    if isinstance(value, _strings):
        return mask_text(value)
    return value
