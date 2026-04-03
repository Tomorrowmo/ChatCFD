from post_service.algorithms.render import NAME, DESCRIPTION, DEFAULTS


class TestRenderMetadata:
    def test_name(self):
        assert NAME == "render"

    def test_defaults(self):
        assert "scalar" in DEFAULTS
        assert "width" in DEFAULTS
        assert "height" in DEFAULTS

    def test_defaults_is_dict(self):
        assert isinstance(DEFAULTS, dict)
