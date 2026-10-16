import json
from types import SimpleNamespace as NS
from unittest.mock import patch
from autodrive_console.map_snapshot import ObservationMapSnapshot

def grid(cells):
    return NS(info=NS(resolution=.1,width=2,height=2,origin=NS(position=NS(x=0,y=0)),
        map_load_time=NS(sec=0,nanosec=0)),header=NS(frame_id='map'),data=cells)

def test_different_cells_with_identical_map_metadata_replace_active_map(tmp_path):
    snapshot=ObservationMapSnapshot(tmp_path)
    with patch.object(snapshot._cache,'find_matching_map',return_value=None):
        snapshot._on_map(grid([0,0,0,0]));first=snapshot.status()['active_map_id']
        snapshot._on_map(grid([100,100,100,100]));second=snapshot.status()['active_map_id']
    assert first != second
    assert json.loads((tmp_path/'active_map.json').read_text())['asset_id']==second

def test_identical_map_replay_does_not_rewrite_assets(tmp_path):
    snapshot=ObservationMapSnapshot(tmp_path)
    with patch.object(snapshot._cache,'find_matching_map',return_value=None), \
         patch.object(snapshot._cache,'cache_occupancy_grid',wraps=snapshot._cache.cache_occupancy_grid) as cache:
        snapshot._on_map(grid([0,0,0,0]));snapshot._on_map(grid([0,0,0,0]))
        assert cache.call_count==1

def test_stop_timeout_keeps_worker_owned_and_cannot_clear_its_stop_token(tmp_path):
    import threading
    started,release=threading.Event(),threading.Event()
    class SlowSnapshot(ObservationMapSnapshot):
        calls=0
        def _run(self):
            self.calls+=1;started.set();release.wait(2)
            while not self._stop.wait(.01):pass
    snapshot=SlowSnapshot(tmp_path);snapshot.start();assert started.wait(1)
    old=snapshot._thread
    try:
        with patch.object(old,'join',return_value=None):snapshot.stop()
        assert old.is_alive()
        assert snapshot._thread is old
        snapshot.start()
        assert snapshot._thread is old and snapshot._stop.is_set() and snapshot.calls==1
    finally:
        release.set();snapshot.stop();old.join(2)
    snapshot.start()
    try:assert snapshot._thread is not old
    finally:snapshot.stop()

def test_stopped_map_callback_cannot_publish_active_marker(tmp_path):
    import threading
    entered,resume=threading.Event(),threading.Event()
    snapshot=ObservationMapSnapshot(tmp_path)
    original=snapshot._cache.cache_occupancy_grid
    def delayed(**kwargs):
        asset=original(**kwargs);entered.set();assert resume.wait(2);return asset
    with patch.object(snapshot._cache,'find_matching_map',return_value=None), \
         patch.object(snapshot._cache,'cache_occupancy_grid',side_effect=delayed):
        worker=threading.Thread(target=lambda:snapshot._on_map(grid([0]*4)))
        snapshot._thread=worker;worker.start();assert entered.wait(1)
        try:
            with patch.object(worker,'join',return_value=None):snapshot.stop()
        finally:resume.set();worker.join(2)
    assert not (tmp_path/'active_map.json').exists()
    assert snapshot.status()['state']!='ready'
