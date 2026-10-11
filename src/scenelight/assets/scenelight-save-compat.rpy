# SceneLight save compatibility bridge
#
# Ren'Py 7 can open saves made by Ren'Py 6, but the reverse is not normally
# true. SceneLight leaves this small bridge only when a legacy game has newer
# saves at removal time. It maps renamed engine objects back to their Ren'Py 6
# equivalents; it does not add lighting or change game content.

init -999 python:
    import sys as _scenelight_sys
    import types as _scenelight_types

    if int(getattr(renpy, "version_tuple", (0,))[0]) < 7:
        def _scenelight_compat_module(name, attributes):
            module = _scenelight_sys.modules.get(name)
            if module is None:
                module = _scenelight_types.ModuleType(name.encode("ascii"))
                _scenelight_sys.modules[name] = module
            for key, value in attributes.items():
                setattr(module, key, value)
            parent_name, child_name = name.rsplit(".", 1)
            parent = _scenelight_sys.modules.get(parent_name)
            if parent is not None:
                setattr(parent, child_name, module)
            return module

        _scenelight_compat_module(
            "renpy.revertable",
            {
                "CompressedList": renpy.python.CompressedList,
                "RevertableDict": renpy.python.RevertableDict,
                "RevertableList": renpy.python.RevertableList,
                "RevertableObject": renpy.python.RevertableObject,
                "RevertableSet": renpy.python.RevertableSet,
            },
        )
        _scenelight_compat_module(
            "renpy.rollback",
            {
                "Rollback": renpy.python.Rollback,
                "RollbackLog": renpy.python.RollbackLog,
                "deleted": renpy.python.deleted,
            },
        )
        _scenelight_compat_module(
            "renpy.display.scenelists",
            {
                "SceneListEntry": renpy.display.core.SceneListEntry,
                "SceneLists": renpy.display.core.SceneLists,
            },
        )
        _scenelight_compat_module(
            "renpy.display.matrix",
            {
                "Matrix": renpy.display.render.Matrix2D,
                "Matrix2D": renpy.display.render.Matrix2D,
            },
        )
        _scenelight_compat_module(
            "renpy.display.displayable",
            {
                "DisplayableArguments": renpy.display.core.DisplayableArguments,
            },
        )

        class _SceneLightParameter(object):
            POSITIONAL_ONLY = 0
            POSITIONAL_OR_KEYWORD = 1
            VAR_POSITIONAL = 2
            KEYWORD_ONLY = 3
            VAR_KEYWORD = 4
            empty = None

            def __setstate__(self, state):
                values = state[1] if isinstance(state, tuple) else state
                if not isinstance(values, dict):
                    values = {}
                self.name = values.get("name")
                self.kind = values.get("kind", self.POSITIONAL_OR_KEYWORD)
                self.default = values.get("default")

        class _SceneLightValuedParameter(_SceneLightParameter):
            pass

        class _SceneLightSignature(object):
            def __setstate__(self, state):
                values = state[1] if isinstance(state, tuple) else state
                if not isinstance(values, dict):
                    values = {}
                parameters = values.get("parameters", {})
                if not hasattr(parameters, "items"):
                    parameters = {}
                self.parameters = []
                self.positional = []
                self.extrapos = None
                self.extrakw = None
                for name, parameter in parameters.items():
                    kind = getattr(
                        parameter,
                        "kind",
                        _SceneLightParameter.POSITIONAL_OR_KEYWORD,
                    )
                    default = getattr(parameter, "default", None)
                    if kind == _SceneLightParameter.VAR_POSITIONAL:
                        self.extrapos = name
                    elif kind == _SceneLightParameter.VAR_KEYWORD:
                        self.extrakw = name
                    else:
                        self.parameters.append((name, default))
                        if kind in (
                            _SceneLightParameter.POSITIONAL_ONLY,
                            _SceneLightParameter.POSITIONAL_OR_KEYWORD,
                        ):
                            self.positional.append(name)

            def __reduce__(self):
                return (
                    renpy.ast.ParameterInfo,
                    (
                        self.parameters,
                        self.positional,
                        self.extrapos,
                        self.extrakw,
                    ),
                )

        _scenelight_compat_module(
            "renpy.parameter",
            {
                "Parameter": _SceneLightParameter,
                "ValuedParameter": _SceneLightValuedParameter,
                "Signature": _SceneLightSignature,
            },
        )

        _scenelight_original_pyexpr = renpy.ast.PyExpr

        class _SceneLightPyExpr(_scenelight_original_pyexpr):
            def __new__(cls, source, filename, linenumber, py=2):
                return _scenelight_original_pyexpr.__new__(
                    cls,
                    source,
                    filename,
                    linenumber,
                )

        _SceneLightPyExpr.__module__ = "renpy.ast".encode("ascii")
        _SceneLightPyExpr.__name__ = "PyExpr".encode("ascii")
        renpy.ast.PyExpr = _SceneLightPyExpr
