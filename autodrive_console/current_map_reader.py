"""Fresh map reads through a retained, independently owned ROS client."""
from pathlib import Path
import logging
import hashlib
import math
import threading

from .map_assets import MapAssetCache

LOGGER = logging.getLogger('ry_aletheia.manual_relocalization')


class CurrentMapUnavailable(RuntimeError):
    pass


class CurrentMapReader:
    def __init__(self):
        self._lock = threading.RLock()
        self._node = self._client = self._executor = None
        self._closed = False
        self._grid_client = None
        self._grid_signature = None
        self._source_map_id = None
        self._active_path = None
        self._allow_change = False

    def _connect(self):
        if self._node is not None:
            return
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rcl_interfaces.srv import GetParameters
        if not rclpy.ok():
            rclpy.init()
        node = rclpy.create_node('ry_aletheia_relocalization_map')
        executor = None
        try:
            executor = SingleThreadedExecutor()
            executor.add_node(node)
            client = node.create_client(GetParameters, '/map_server/get_parameters')
        except Exception:
            if executor is not None:
                executor.shutdown()
            node.destroy_node()
            raise
        self._node, self._executor, self._client = node, executor, client

    def _read_parameter(self) -> Path:
        with self._lock:
            if self._closed:
                raise CurrentMapUnavailable('当前地图无法确认')
            try:
                from rcl_interfaces.msg import ParameterType
                from rcl_interfaces.srv import GetParameters
                self._connect()
                if not self._client.wait_for_service(timeout_sec=3.0):
                    raise CurrentMapUnavailable('当前地图服务未就绪')
                for attempt in range(2):
                    future = self._client.call_async(GetParameters.Request(names=['yaml_filename']))
                    self._executor.spin_until_future_complete(future, timeout_sec=5.0)
                    if future.done():
                        response = future.result()
                        break
                    future.cancel()
                    if attempt:
                        raise CurrentMapUnavailable('当前地图查询响应超时')
                    LOGGER.warning('当前地图首次只读查询超时，正在重新查询')
                if response is None or len(response.values) != 1:
                    raise CurrentMapUnavailable('当前地图参数无效')
                parameter = response.values[0]
                if parameter.type != ParameterType.PARAMETER_STRING or not parameter.string_value.strip():
                    raise CurrentMapUnavailable('当前地图参数无效')
                raw = Path(parameter.string_value.strip())
                if not raw.is_absolute() or '..' in raw.parts:
                    raise CurrentMapUnavailable('当前地图路径不受支持')
                path = raw.resolve(strict=True)
                root = MapAssetCache.ALLOWED_ROOTS[0].resolve()
                if not path.is_file() or path.suffix not in {'.yaml', '.yml'} or not path.is_relative_to(root):
                    raise CurrentMapUnavailable('当前地图路径不受支持')
                return path
            except CurrentMapUnavailable:
                raise
            except Exception as exc:
                raise CurrentMapUnavailable('当前地图无法确认') from exc

    @staticmethod
    def grid_signature(grid):
        try:
            info, header = grid.info, grid.header
            p, q = info.origin.position, info.origin.orientation
            values = tuple(float(v) for v in (info.resolution,p.x,p.y,p.z,q.x,q.y,q.z,q.w))
            if not all(math.isfinite(v) for v in values) or values[0] <= 0:
                raise ValueError()
            if info.width <= 0 or info.height <= 0 or len(grid.data) != info.width * info.height:
                raise ValueError()
            try:
                data = memoryview(grid.data).cast('B')
            except TypeError:
                data = bytes(int(v) & 255 for v in grid.data)
            return (str(header.frame_id),int(info.width),int(info.height),*values,hashlib.sha256(data).digest())
        except (AttributeError,TypeError,ValueError,OverflowError) as exc:
            raise CurrentMapUnavailable('当前二维地图数据无效') from exc

    def _read_grid(self):
        if self._closed: raise CurrentMapUnavailable("当前地图无法确认")
        from nav_msgs.srv import GetMap
        self._connect()
        if self._grid_client is None:
            self._grid_client = self._node.create_client(GetMap, '/map_server/map')
        if not self._grid_client.wait_for_service(timeout_sec=3.0):
            raise CurrentMapUnavailable('当前二维地图服务未就绪')
        for attempt in range(2):
            future = self._grid_client.call_async(GetMap.Request())
            self._executor.spin_until_future_complete(future, timeout_sec=5.0)
            if future.done():
                response = future.result()
                grid = getattr(response, 'map', None)
                self.grid_signature(grid)
                return grid
            future.cancel()
            if attempt: raise CurrentMapUnavailable('当前二维地图查询超时')
            LOGGER.warning('当前二维地图首次只读查询超时，正在重新查询')

    def start(self) -> Path:
        """Bind live grid evidence; yaml_filename is only an initial path hint."""
        with self._lock:
            path = self._read_parameter()
            grid = self._read_grid()
            signature = self.grid_signature(grid)
            source_map_id = self._asset_id(grid)
            if self._active_path is not None and signature == self._grid_signature:
                path = self._active_path
            self._active_path, self._grid_signature = path, signature
            self._source_map_id = source_map_id
            self._allow_change = False
            return path

    @property
    def source_map_id(self):
        with self._lock:
            return self._source_map_id

    @staticmethod
    def _asset_id(grid):
        info = grid.info
        p, q = info.origin.position, info.origin.orientation
        if (any(abs(float(v)) > 1e-6 for v in (p.z, q.x, q.y, q.z))
                or abs(abs(float(q.w)) - 1.0) > 1e-6):
            raise CurrentMapUnavailable('当前二维地图原点不受手动重定位支持')
        identity, _ = MapAssetCache.occupancy_grid_identity(
            resolution=float(info.resolution), width=int(info.width), height=int(info.height),
            origin=[float(p.x), float(p.y)], frame_id=str(grid.header.frame_id).strip() or 'map', data=grid.data)
        return identity

    def read(self) -> Path:
        with self._lock:
            if self._closed: raise CurrentMapUnavailable('当前地图无法确认')
            if self._grid_signature is None:
                return self._read_parameter()
            signature = self.grid_signature(self._read_grid())
            if signature != self._grid_signature and not self._allow_change:
                raise CurrentMapUnavailable('当前二维地图已变化')
            return self._active_path

    def allow_map_change(self):
        with self._lock: self._allow_change = True

    def bind_loaded_map(self, target: Path, response_grid):
        with self._lock:
            expected = self.grid_signature(response_grid)
            actual = self.grid_signature(self._read_grid())
            if actual != expected:
                raise CurrentMapUnavailable('二维地图切换后当前地图未确认')
            self._active_path, self._grid_signature = target, actual
            self._source_map_id = self._asset_id(response_grid)
            self._allow_change = False

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self._executor is not None:
                    self._executor.shutdown()
            finally:
                if self._node is not None:
                    self._node.destroy_node()
                self._node = self._client = self._executor = self._grid_client = None
