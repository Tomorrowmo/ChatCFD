from post_service.algorithms.slice import NAME, DESCRIPTION, DEFAULTS


class TestSliceMetadata:
    def test_name(self):
        assert NAME == "slice"

    def test_defaults(self):
        assert "origin" in DEFAULTS
        assert "normal" in DEFAULTS

    def test_defaults_is_dict(self):
        assert isinstance(DEFAULTS, dict)
