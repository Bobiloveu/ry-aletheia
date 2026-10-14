"""Isolate the default service Store before pytest imports HTTP test modules.

web_console constructs MapProjectionJobs at import time; its startup scan may
migrate projects. Fixture/HTTP mocks applied after collection are too late.
Only the actual repository deployment root is redirected. Explicit temporary
fixture Stores and all application code retain their normal behavior.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from deployment_test_workspace import isolated_default_deployments


def pytest_configure(config):
    temporary=TemporaryDirectory(prefix='ry-test-service-')
    guard=isolated_default_deployments(Path(__file__).resolve().parents[1]/'deployments',Path(temporary.name)/'deployments')
    guard.__enter__()
    config.add_cleanup(temporary.cleanup)
    config.add_cleanup(lambda:guard.__exit__(None,None,None))
    # web_console configures logging before recovering services. Keep those
    # startup records and subsequent test operations out of the real tool logs.
    from autodrive_console.tool_logging import ToolLogStore
    original = ToolLogStore.__init__
    default_logs = Path(__file__).resolve().parents[1] / "logs"
    def initialize(store, directory):
        target = Path(temporary.name) / "logs" if Path(directory).resolve() == default_logs.resolve() else directory
        original(store, target)
    logs_guard = patch.object(ToolLogStore, "__init__", initialize)
    logs_guard.start()
    config.add_cleanup(logs_guard.stop)
