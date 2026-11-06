import copy
import hashlib
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from zipfile import ZipFile

import av
import cv2
import numpy as np
import pytest

from selection.opacity_package import export_opacity_package
from tests.test_video_orientation import oriented_movie


def measured_record(source):
    keys = [{'source_time': 0., 'opacity_percent': 0.},
            {'source_time': 1 / 24, 'opacity_percent': 52.},
            {'source_time': 2 / 24, 'opacity_percent': 100.}]
    return {'id': '示例/记录', 'kind': 'clip', 'status': 'done',
            'source_hash': hashlib.sha256(source.read_bytes()).hexdigest(),
            'result': {'time': {'start': 0., 'end': .125},
                       'opacity_blend': {'method': 'two-held-pictures-v1', 'keyframes': keys}}}


def test_retry_on_rotated_anamorphic_source_keeps_complete_portable_package(tmp_path):
    source = oriented_movie(tmp_path / '原片.mp4', 90, shifted=True, sar=Fraction(2))
    record, destination = measured_record(source), tmp_path / '导出'
    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda _: export_opacity_package(record, source, destination), range(2)))
    assert paths[0] == paths[1] and list(destination.iterdir()) == [paths[0]]
    saved = paths[0].read_bytes()
    with av.open(str(source)) as media, ZipFile(paths[0]) as archive:
        frames = list(media.decode(video=0))
        assert archive.testzip() is None
        for name, frame in [('start.png', frames[0]), ('reference.png', frames[1]), ('end.png', frames[-1])]:
            encoded = frame.to_ndarray(format='bgr24')
            expected = np.rot90(cv2.resize(encoded, (96, 32), interpolation=cv2.INTER_LINEAR))
            actual = cv2.imdecode(np.frombuffer(archive.read(name), dtype=np.uint8), cv2.IMREAD_COLOR)
            assert np.array_equal(actual, expected)
    # Failure after opening the temporary archive must not replace the previous export.
    wrong = copy.deepcopy(record)
    wrong['result']['opacity_blend']['keyframes'][1]['source_time'] = .03
    with pytest.raises(ValueError, match='关键帧'):
        export_opacity_package(wrong, source, destination)
    assert paths[0].read_bytes() == saved and list(destination.iterdir()) == [paths[0]]
    source.write_bytes(b'replaced')
    with pytest.raises(ValueError, match='不匹配'):
        export_opacity_package(record, source, destination)
    assert paths[0].read_bytes() == saved


def test_comparison_uses_real_middle_frame_between_reduced_keys(tmp_path):
    source = oriented_movie(tmp_path/'source.mp4', 0)
    record = measured_record(source)
    record['result']['opacity_blend']['keyframes'].pop(1)
    package = export_opacity_package(record, source, tmp_path/'export')
    with av.open(str(source)) as media, ZipFile(package) as archive:
        expected = list(media.decode(video=0))[1].to_ndarray(format='bgr24')
        actual = cv2.imdecode(np.frombuffer(archive.read('reference.png'), np.uint8), cv2.IMREAD_COLOR)
        assert np.array_equal(actual, expected)
        instructions = archive.read('使用说明.txt').decode()
        assert '0.041667' in instructions and '50.00%' in instructions


@pytest.mark.parametrize('result', [None, [], {}, {'opacity_blend': 'legacy'},
                                    {'opacity_blend': {'method': 'other', 'keyframes': []}}])
def test_unavailable_history_does_not_create_output(result, tmp_path):
    record = {'result': result, 'kind': 'clip', 'status': 'done'}
    with pytest.raises(ValueError, match='叠化'):
        export_opacity_package(record, tmp_path/'missing', tmp_path/'exports')
    assert not (tmp_path/'exports').exists()
