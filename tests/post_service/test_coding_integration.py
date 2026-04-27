"""Integration test: runBash and runPython tools via engine."""

import os

from post_service.mcp_tools.run_bash import _run_command
from post_service.mcp_tools.run_python import _run_python


class TestCodingIntegration:
    def test_bash_echo_roundtrip(self):
        result = _run_command("echo integration_test", timeout=10)
        assert result["exit_code"] == 0
        assert "integration_test" in result["stdout"]

    def test_python_matplotlib_save(self, tmp_path):
        """Full flow: Python generates a plot, saves to file, reports path."""
        out = str(tmp_path / "test_plot.png").replace("\\", "/")
        code = (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "import numpy as np\n"
            "x = np.linspace(0, 10, 50)\n"
            "plt.plot(x, np.sin(x))\n"
            f"plt.savefig(r'{out}')\n"
            f"print(f'CHATCFD_OUTPUT_FILE:{out}')\n"
            "print('done')\n"
        )
        result = _run_python(code, timeout=30)
        assert result["exit_code"] == 0, f"stderr: {result['stderr']}"
        assert "done" in result["stdout"]
        assert len(result["output_files"]) == 1
        assert os.path.exists(out)

    def test_harness_blocks_then_allows(self):
        """Verify Harness blocks runBash without confirm, allows with."""
        from agent.harness import Harness
        h = Harness()
        r1 = h.before_call("runBash", {"command": "echo test"}, user_confirmed_coding=False)
        assert r1 is not None
        r2 = h.before_call("runBash", {"command": "echo test"}, user_confirmed_coding=True)
        assert r2 is None

    def test_mcp_tools_importable(self):
        """Verify both tools can be imported via the registry."""
        from post_service.mcp_tools import register_all
        assert callable(register_all)
