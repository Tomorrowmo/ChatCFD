"""MCP tool thin shells — each module exposes register(mcp, engine)."""

from post_service.mcp_tools.load_file import register as register_load_file
from post_service.mcp_tools.calculate import register as register_calculate
from post_service.mcp_tools.compare import register as register_compare
from post_service.mcp_tools.export_data import register as register_export_data
from post_service.mcp_tools.list_files import register as register_list_files
from post_service.mcp_tools.get_method_template import register as register_get_method_template


def register_all(mcp, engine):
    """Register all 6 MCP tools on the given FastMCP instance."""
    register_load_file(mcp, engine)
    register_calculate(mcp, engine)
    register_compare(mcp, engine)
    register_export_data(mcp, engine)
    register_list_files(mcp, engine)
    register_get_method_template(mcp, engine)
