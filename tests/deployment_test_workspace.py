"""Prevent service import/adoption from touching real deployment projects."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from autodrive_console.deployment import DeploymentStore


@contextmanager
def isolated_default_deployments(default_root, private_root):
    original=DeploymentStore.__init__
    expected=Path(default_root).resolve()
    def initialize(self,root):
        return original(self,Path(private_root) if Path(root).resolve()==expected else root)
    with patch.object(DeploymentStore,'__init__',initialize):
        yield
