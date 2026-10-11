from scenelight.runtime.live_gpu import FLOAT, RG32F, RGBA8, Device


class Driver:
    def __init__(self):
        self.es = False
        self.calls = []

    def generate(self, kind):
        return 7

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, args))


def device_fixture():
    device = Device.__new__(Device)
    device.gl = Driver()
    device.opencl = None
    device.targets = {"source": (7, 2, 2, RGBA8, False)}
    device._attachments = [7, 0, 0, 0]
    device._draw_count = 1
    device._validated = {(7, 0, 0, 0)}
    device.fbo = 3
    device.vao = 5
    return device


def test_resizing_reattaches_texture_when_driver_reuses_a_deleted_name():
    device = device_fixture()
    texture = device.target("source", 3, 3, RGBA8)
    assert texture == 7
    device.bind_targets((texture,))
    attachments = [args for name, args in device.gl.calls if name == "FramebufferTexture2D"]
    assert any(args[3] == 7 for args in attachments)
    assert not device._validated


def test_complex_targets_use_es_compatible_rg_float_allocation():
    device = device_fixture()
    device.target("complex", 8, 8, RG32F)
    allocation = next(args for name, args in device.gl.calls if name == "TexImage2D")
    assert allocation[2] == RG32F
    assert allocation[6:8] == (0x8227, FLOAT)


def test_resizing_releases_shared_reference_before_gl_texture():
    device = device_fixture()

    class Sharing:
        def release_texture(self, texture):
            device.gl.calls.append(("release_shared", (texture,)))

    device.opencl = Sharing()
    device.target("source", 3, 3, RGBA8)
    shared = device.gl.calls.index(("release_shared", (7,)))
    deleted = device.gl.calls.index(("delete", ("Textures", 7)))
    assert shared < deleted


def test_blended_mrt_clears_every_accumulation_target():
    device = device_fixture()
    device._validated.add((7, 8, 0, 0))
    device.draw(9, 7, 2, 2, points=4, blend=True, extra_targets=(8,))
    cleared = [args[1] for name, args in device.gl.calls if name == "ClearBufferfv"]
    assert cleared == [0, 1]
