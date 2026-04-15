from post_service.algorithms.rtslice import NAME, DESCRIPTION, DEFAULTS


class TestSliceMetadata:
    def test_name(self):
        assert NAME == "slice"

    def test_defaults(self):
        assert "direction" in DEFAULTS
        assert "n_slices" in DEFAULTS

    def test_defaults_is_dict(self):
        assert isinstance(DEFAULTS, dict)
