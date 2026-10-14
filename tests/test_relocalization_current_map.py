"""Exercise the direct ROS parameter-service boundary without connecting to a robot."""
import sys
from array import array
from pathlib import Path
from types import SimpleNamespace

import pytest

import autodrive_console.current_map_reader as module
from autodrive_console.current_map_reader import CurrentMapReader, CurrentMapUnavailable


def parameter(value, kind=4):
    return SimpleNamespace(type=kind, string_value=value, bool_value=False, integer_value=0,
                           double_value=0.0, byte_array_value=[], bool_array_value=[],
                           integer_array_value=[], double_array_value=[], string_array_value=[])


def grid(value=0):
    return SimpleNamespace(header=SimpleNamespace(frame_id='map'),
        info=SimpleNamespace(width=2,height=2,resolution=.05,
            origin=SimpleNamespace(position=SimpleNamespace(x=0.,y=0.,z=0.),
                orientation=SimpleNamespace(x=0.,y=0.,z=0.,w=1.))),
        data=array('b',[value,0,100,-1]))


@pytest.fixture
def ros_parameter_service(tmp_path, monkeypatch):
    root = tmp_path / "maps"
    current = root / "P2" / "map.yaml"
    current.parent.mkdir(parents=True)
    current.write_text("image: map.pgm\n")
    state = {"ready": True, "done": True, "response": SimpleNamespace(values=[parameter(str(current))]),
             "destroyed": False, "cancelled": False, "calls": 0, "created": 0, "retry_succeeds": False, "grid":grid(), "grid_calls":0}
    monkeypatch.setattr(module.MapAssetCache, "ALLOWED_ROOTS", (root,))

    class Future:
        def done(self):
            return state["done"] or state["retry_succeeds"] and state["calls"] > 1

        def result(self):
            return state["response"]

        def cancel(self):
            state["cancelled"] = True

    class GetParameters:
        Request = SimpleNamespace
    class GetMap:
        Request = SimpleNamespace

    class Client:
        def wait_for_service(self, *, timeout_sec):
            assert 0 < timeout_sec <= 5
            return state["ready"]

        def call_async(self, request):
            assert request.names == ["yaml_filename"]
            state["calls"] += 1
            return Future()

    class GridClient:
        def wait_for_service(self, *, timeout_sec): return state['ready']
        def call_async(self, request):
            state['grid_calls'] += 1
            return SimpleNamespace(done=lambda:True,result=lambda:SimpleNamespace(map=state['grid']),cancel=lambda:None)
    class Node:
        def create_client(self, kind, name):
            if kind is GetMap:
                assert name == '/map_server/map'
                return GridClient()
            assert kind is GetParameters
            assert name == "/map_server/get_parameters"
            return Client()

        def destroy_node(self):
            state["destroyed"] = True

    class Executor:
        def add_node(self, node): pass
        def spin_until_future_complete(self, future, *, timeout_sec):
            assert 0 < timeout_sec <= 5
        def shutdown(self): pass
    def create(name):
        state["created"] += 1
        return Node()
    monkeypatch.setitem(sys.modules, "rclpy", SimpleNamespace(ok=lambda: True, create_node=create))
    monkeypatch.setitem(sys.modules, "rclpy.executors", SimpleNamespace(SingleThreadedExecutor=Executor))
    monkeypatch.setitem(sys.modules, "rcl_interfaces.msg", SimpleNamespace(
        ParameterType=SimpleNamespace(PARAMETER_STRING=4)))
    monkeypatch.setitem(sys.modules, "rcl_interfaces.srv", SimpleNamespace(GetParameters=GetParameters))
    monkeypatch.setitem(sys.modules, "nav_msgs.srv", SimpleNamespace(GetMap=GetMap))
    reader = CurrentMapReader()
    yield state, current, reader
    reader.close()


def test_map_query_reads_live_parameter_each_time_and_destroys_node(ros_parameter_service):
    state, current, reader = ros_parameter_service
    assert reader.read() == current
    assert not state["destroyed"]
    other = current.parent.parent / "P1" / "map.yaml"
    other.parent.mkdir()
    other.write_text("image: map.pgm\n")
    state["response"] = SimpleNamespace(values=[parameter(str(other))])
    assert reader.read() == other
    assert state["created"] == 1
    assert state["calls"] == 2
    reader.close()
    assert state["destroyed"]


@pytest.mark.parametrize("failure", ["missing", "timeout", "no_response", "empty", "wrong_type",
                                     "blank", "relative", "outside", "symlink", "nonexistent"])
def test_map_query_fails_closed_without_cached_or_startup_fallback(ros_parameter_service, failure):
    state, current, reader = ros_parameter_service
    if failure == "missing":
        state["ready"] = False
    elif failure == "timeout":
        state["done"] = False
    elif failure == "no_response":
        state["response"] = None
    elif failure == "empty":
        state["response"].values = []
    elif failure == "wrong_type":
        state["response"].values = [parameter(str(current), 0)]
    else:
        value = {"blank": " ", "relative": "P2/map.yaml", "outside": "/etc/passwd",
                 "nonexistent": str(current.parent / "missing.yaml")}.get(failure)
        if failure == "symlink":
            outside = current.parents[2] / "outside.yaml"
            outside.write_text("image: map.pgm\n")
            link = current.parent / "escape.yaml"
            link.symlink_to(outside)
            value = str(link)
        state["response"].values = [parameter(value)]
    with pytest.raises(CurrentMapUnavailable):
        reader.read()
    reader.close()
    assert state["destroyed"]
    if failure == "timeout":
        assert state["cancelled"]


def test_first_read_timeout_retries_one_new_request_and_keeps_the_connection(ros_parameter_service):
    state, current, reader = ros_parameter_service
    state['done'] = False
    state['retry_succeeds'] = True
    assert reader.read() == current
    assert state['calls'] == 2 and state['cancelled']
    assert state['created'] == 1


def test_two_read_timeouts_fail_without_any_cached_map(ros_parameter_service):
    state, current, reader = ros_parameter_service
    assert reader.read() == current
    state['done'] = False
    with pytest.raises(CurrentMapUnavailable, match='超时'): reader.read()
    assert state['calls'] == 3


def test_load_map_confirmation_uses_live_grid_when_yaml_parameter_stays_at_startup(ros_parameter_service):
    state,current,reader=ros_parameter_service
    assert reader.start()==current
    target=current.parent.parent/'P1'/'map.yaml';target.parent.mkdir();target.write_text('image: map.pgm\n')
    reader.allow_map_change();state['grid']=grid(100)
    reader.bind_loaded_map(target,state['grid'])
    assert state['response'].values[0].string_value==str(current)
    assert reader.read()==target
    assert reader.start()==target
    state['grid']=grid(25)
    with pytest.raises(CurrentMapUnavailable,match='变化'):reader.read()
    # A new manual operation can bind externally changed real grid again.
    assert reader.start()==current


def test_load_map_success_with_a_different_live_grid_is_rejected(ros_parameter_service):
    state,current,reader=ros_parameter_service
    reader.start()
    with pytest.raises(CurrentMapUnavailable,match='未确认'):
        reader.bind_loaded_map(current,grid(100))


def test_runtime_asset_identity_matches_existing_cache_without_writing(tmp_path):
    cache=module.MapAssetCache(tmp_path/'cache');m=grid(50);i=m.info
    args=dict(resolution=i.resolution,width=i.width,height=i.height,origin=[0.,0.],frame_id='map',data=m.data)
    identity,_=cache.occupancy_grid_identity(**args)
    assert not cache.cache_dir.exists()
    assert cache.cache_occupancy_grid(**args).id==identity


def test_source_map_id_is_bound_to_the_actual_get_map_grid(ros_parameter_service):
    state,current,reader=ros_parameter_service
    reader.start()
    item=state['grid']; info=item.info
    expected,_=module.MapAssetCache.occupancy_grid_identity(resolution=info.resolution,
        width=info.width,height=info.height,origin=[0.,0.],frame_id='map',data=item.data)
    assert reader.source_map_id == expected
    state['grid']=grid(100)
    reader.start()
    assert reader.source_map_id != expected


@pytest.mark.parametrize('kind', ['yaw','tilt','nonunit','height'])
def test_manual_map_binding_rejects_origins_the_pc_cannot_render(ros_parameter_service,kind):
    state,_current,reader=ros_parameter_service
    origin=state['grid'].info.origin
    if kind=='yaw': origin.orientation.z=.70710678; origin.orientation.w=.70710678
    if kind=='tilt': origin.orientation.x=.1
    if kind=='nonunit': origin.orientation.w=0.
    if kind=='height': origin.position.z=1.
    with pytest.raises(CurrentMapUnavailable,match='原点'): reader.start()
