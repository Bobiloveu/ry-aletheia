from pathlib import Path
from unittest.mock import patch

from autodrive_console.deployment import DeploymentStore


def test_service_default_store_is_redirected_before_boot_scans(tmp_path):
    from deployment_test_workspace import isolated_default_deployments
    default=tmp_path/'working-project'/'deployments'
    private=tmp_path/'private'/'deployments'
    with isolated_default_deployments(default,private):
        service=DeploymentStore(default)
        assert service.root==private
        other=DeploymentStore(tmp_path/'fixture')
        assert other.root==tmp_path/'fixture'
        with patch.object(DeploymentStore,'get',side_effect=AssertionError('must not read a project')):
            assert service.list_projects()==[]
    assert not default.exists()
