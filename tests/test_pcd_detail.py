import numpy as np
import pytest
from pypcd4 import PointCloud, Encoding
from autodrive_console import pcd_projection as core

DTYPE = np.dtype([('xyz','<f4',(3,)),('rgba','u1',(4,)),('intensity','<f4')])

@pytest.mark.parametrize('encoding', [Encoding.ASCII, Encoding.BINARY, Encoding.BINARY_COMPRESSED])
@pytest.mark.parametrize('packed', ['rgb', 'rgba'])
def test_detail_preserves_pcl_packed_colors_intensity_and_finite_alignment(tmp_path, encoding, packed):
    source=tmp_path/'color.pcd'
    bits=np.array([0xff112233,0xffaabbcc,0xff778899],dtype=np.uint32)
    points=np.zeros(3,dtype=[('x','f4'),('y','f4'),('z','f4'),(packed,'f4'),('Intensity','f4')])
    points['x']=[0,np.nan,2]; points['z']=[0,1,2]
    points[packed]=bits.view('f4');points['Intensity']=[10,20,30]
    # ASCII cannot preserve NaN payloads in packed RGBA; use conventional RGB float bits there.
    if encoding==Encoding.ASCII:
        points[packed]=(bits & 0xffffff).view('f4')
    PointCloud.from_points(tuple(points[n] for n in points.dtype.names), points.dtype.names, tuple(points.dtype[n] for n in points.dtype.names)).save(source,encoding)
    if encoding == Encoding.ASCII:
        # pypcd4's default fixed-decimal writer rounds packed subnormal RGB to zero.
        header=source.read_bytes().split(b'DATA ascii\n')[0]+b'DATA ascii\n'
        rows=[' '.join(format(float(points[n][i]), '.9e') for n in points.dtype.names) for i in range(3)]
        source.write_bytes(header+('\n'.join(rows)+'\n').encode())
    before=source.read_bytes(); output=tmp_path/'detail.bin'
    meta=core.build_source_detail(source,output)
    data=np.frombuffer(output.read_bytes(),dtype=DTYPE)
    assert meta['point_count']==2
    assert meta['attributes']['rgb'] and meta['attributes']['intensity']
    assert data['rgba'].tolist()==[[17,34,51,255],[119,136,153,255]]
    assert data['intensity'].tolist()==[10,30]
    assert data['xyz'].tolist()==[[-1,0,-1],[1,0,1]]
    assert source.read_bytes()==before


def test_detail_keeps_more_than_old_100k_limit_and_is_deterministic(tmp_path):
    xyz=np.zeros((120001,3),dtype='f4');xyz[:,0]=np.arange(len(xyz))
    source=tmp_path/'large.pcd';PointCloud.from_xyz_points(xyz).save(source,Encoding.BINARY)
    first,second=tmp_path/'one.bin',tmp_path/'two.bin'
    meta=core.build_source_detail(source,first);core.build_source_detail(source,second)
    assert meta['point_count']==len(xyz)
    assert len(first.read_bytes())==len(xyz)*20
    assert first.read_bytes()==second.read_bytes()
    data=np.frombuffer(first.read_bytes(),dtype=DTYPE)
    assert not data['rgba'][:,3].any() and np.isnan(data['intensity']).all()
    assert not meta['attributes']['rgb'] and not meta['attributes']['intensity']


def test_detail_independent_rgb_and_outlier_robust_fit(tmp_path):
    fields=('x','y','z','r','g','b','intensity')
    points=np.zeros((1001,7),dtype='f4');points[:1000,0]=np.linspace(0,10,1000);points[-1,0]=100000
    points[:,3:6]=[20,40,60];points[:,6]=np.nan
    source=tmp_path/'channels.pcd';PointCloud.from_points(points,fields,(np.float32,)*7).save(source,Encoding.BINARY)
    meta=core.build_source_detail(source,tmp_path/'detail.bin')
    assert meta['attributes']['display_bounds'][0][1]<11
    assert meta['bounds'][0][1]==100000
    assert meta['attributes']['rgb'] and not meta['attributes']['intensity']


def test_detail_retains_every_point_above_old_two_million_limit(tmp_path):
    xyz = np.zeros((2_000_003, 3), dtype='f4')
    xyz[:, 0] = np.arange(len(xyz))
    source, output = tmp_path/'full.pcd', tmp_path/'full.bin'
    PointCloud.from_xyz_points(xyz).save(source, Encoding.BINARY)
    meta = core.build_source_detail(source, output)
    assert meta['point_count'] == meta['finite_point_count'] == 2_000_003
    rows = np.fromfile(output, dtype=DTYPE)
    assert len(rows) == 2_000_003
    assert np.array_equal(np.diff(rows['xyz'][:, 0]), np.ones(2_000_002))


def test_detail_preserves_float64_local_detail_and_all_finite_attribute_rows(tmp_path):
    source, output = tmp_path/'precise.pcd', tmp_path/'detail.bin'
    fields = ('x','y','z','intensity')
    points = np.array([[1e9,-1e9,0,10],[1e9+.25,-1e9+.5,1,20],
                       [np.nan,0,0,99],[1e9+.5,-1e9+1,2,30]],dtype='f8')
    PointCloud.from_points(points,fields,(np.float64,)*4).save(source,Encoding.BINARY)
    metadata = core.build_source_detail(source,output)
    rows = np.fromfile(output,dtype=DTYPE)
    assert rows['xyz'].tolist() == [[-.25,-.5,-1],[0,0,0],[.25,.5,1]]
    assert rows['intensity'].tolist() == [10,20,30]
    assert metadata['origin'] == [1e9+.25,-1e9+.5,1]
    assert metadata['point_count'] == 3 and metadata['source_point_count'] == 4
