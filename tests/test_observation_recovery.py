from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from autodrive_console.observation import ObservationManager

@pytest.fixture
def running(tmp_path):
    binary=tmp_path/'preprocessor';binary.write_text('test-only executable')
    manager=ObservationManager(tmp_path/'maps',tmp_path/'logs',binary)
    manager._telemetry=Mock();manager._telemetry.status.return_value={'online':True}
    manager._map_snapshot=Mock();manager._map_snapshot.status.return_value={'state':'ready'}
    settings=SimpleNamespace(live_observation={'enabled':True,'idle_stop_seconds':45})
    now=[100.0];created=[]
    def spawn(*args,**kwargs):
        child=Mock(pid=1000+len(created));child.poll.return_value=None
        created.append((args[0],child));return child
    with patch('autodrive_console.observation.time.monotonic',side_effect=lambda:now[0]), \
         patch.object(manager,'_schedule_idle_stop'),patch('autodrive_console.observation.subprocess.Popen',side_effect=spawn), \
         patch('autodrive_console.observation.os.killpg'):
        manager.start(settings)
        try:yield manager,settings,now,created
        finally:manager.stop()

def test_heartbeat_recovers_only_exited_pose_after_backoff(running):
    m,s,now,created=running;cloud=m._preprocessor_processes['cloud'];pose=m._preprocessor_processes['pose']
    pose.poll.return_value=1;pose.returncode=1
    m.heartbeat(s);assert len(created)==3
    now[0]+=1;m.heartbeat(s)
    assert len(created)==4
    assert m._preprocessor_processes['cloud'] is cloud
    assert m._preprocessor_processes['pose'] is not pose
    assert m._telemetry.start.call_count==1

def test_explicit_stop_or_disabled_configuration_never_respawns(running):
    m,s,now,created=running
    m.stop();now[0]+=5;m.heartbeat(s);assert len(created)==3
    m.start(s);count=len(created)
    s.live_observation['enabled']=False
    m._preprocessor_processes['pose'].poll.return_value=1
    now[0]+=5;m.heartbeat(s);assert len(created)==count

def test_repeated_pose_crashes_have_bounded_retry_rate(running):
    m,s,now,created=running
    for n in range(20):
        m._preprocessor_processes.get('pose',Mock()).poll.return_value=1
        now[0]+=.1;m.heartbeat(s)
    assert 3 < len(created) < 8
