from post_service.algorithms.force_moment import NAME, DEFAULTS, execute


class TestForceMomentMetadata:
    def test_name(self):
        assert NAME == "force_moment"

    def test_defaults_is_dict(self):
        assert isinstance(DEFAULTS, dict)

    def test_defaults_has_required(self):
        """density, velocity, refArea must be None (required params)."""
        assert DEFAULTS["density"] is None
        assert DEFAULTS["velocity"] is None
        assert DEFAULTS["refArea"] is None

    def test_has_execute(self):
        assert callable(execute)
