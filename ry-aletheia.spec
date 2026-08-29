# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('autodrive_console/web', 'autodrive_console/web'), ('autodrive_console/web-vue', 'autodrive_console/web-vue'), ('config/video.json', 'config'), ('/tmp/tmp.eFuSxm6MdU/runtime', 'runtime/video')]
binaries = [('/home/bob/Desktop/ry_aletheia_v2/ry-aletheia/build/live_preprocessor/aletheia_live_cloud', '.'), ('/home/bob/Desktop/ry_aletheia_v2/ry-aletheia/build/live_preprocessor/aletheia_video_ingest', '.'), ('/home/bob/Desktop/ry_aletheia_v2/ry-aletheia/install/master_interfaces/lib/libmaster_interfaces__rosidl_generator_c.so', '.'), ('/home/bob/Desktop/ry_aletheia_v2/ry-aletheia/install/master_interfaces/lib/libmaster_interfaces__rosidl_generator_py.so', '.'), ('/home/bob/Desktop/ry_aletheia_v2/ry-aletheia/install/master_interfaces/lib/libmaster_interfaces__rosidl_typesupport_c.so', '.'), ('/home/bob/Desktop/ry_aletheia_v2/ry-aletheia/install/master_interfaces/lib/libmaster_interfaces__rosidl_typesupport_cpp.so', '.'), ('/home/bob/Desktop/ry_aletheia_v2/ry-aletheia/install/master_interfaces/lib/libmaster_interfaces__rosidl_typesupport_fastrtps_c.so', '.'), ('/home/bob/Desktop/ry_aletheia_v2/ry-aletheia/install/master_interfaces/lib/libmaster_interfaces__rosidl_typesupport_fastrtps_cpp.so', '.'), ('/home/bob/Desktop/ry_aletheia_v2/ry-aletheia/install/master_interfaces/lib/libmaster_interfaces__rosidl_typesupport_introspection_c.so', '.'), ('/home/bob/Desktop/ry_aletheia_v2/ry-aletheia/install/master_interfaces/lib/libmaster_interfaces__rosidl_typesupport_introspection_cpp.so', '.'), ('/opt/ros/humble/lib/libtf2_msgs__rosidl_generator_c.so', '.'), ('/opt/ros/humble/lib/libtf2_msgs__rosidl_generator_py.so', '.'), ('/opt/ros/humble/lib/libtf2_msgs__rosidl_typesupport_c.so', '.'), ('/opt/ros/humble/lib/libtf2_msgs__rosidl_typesupport_cpp.so', '.'), ('/opt/ros/humble/lib/libtf2_msgs__rosidl_typesupport_fastrtps_c.so', '.'), ('/opt/ros/humble/lib/libtf2_msgs__rosidl_typesupport_fastrtps_cpp.so', '.'), ('/opt/ros/humble/lib/libtf2_msgs__rosidl_typesupport_introspection_c.so', '.'), ('/opt/ros/humble/lib/libtf2_msgs__rosidl_typesupport_introspection_cpp.so', '.')]
hiddenimports = ['rclpy', 'master_interfaces.srv']
tmp_ret = collect_all('rclpy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tf2_ros')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tf2_py')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tf2_msgs')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rpyutils')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('master_interfaces')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rosidl_parser')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rosidl_runtime_py')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rcl_interfaces')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('builtin_interfaces')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('std_msgs')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('unique_identifier_msgs')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('action_msgs')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('nav_msgs')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('geometry_msgs')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['web_console.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ry-aletheia',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
