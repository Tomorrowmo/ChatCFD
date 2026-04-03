from post_service.algorithms.velocity_gradient import NAME, DEFAULTS, execute


class TestVelocityGradientMetadata:
    def test_name(self):
        assert NAME == "velocity_gradient"

    def test_defaults_is_dict(self):
        assert isinstance(DEFAULTS, dict)

    def test_defaults_has_switches(self):
        assert "mach_switch" in DEFAULTS
        assert "vorticity_switch" in DEFAULTS

    def test_has_execute(self):
        assert callable(execute)
