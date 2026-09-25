"""ffmpeg 输出解析。"""

import pytest

from copernicus.utils.ffmpeg import parse_duration_s

_BANNER = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'v.mp4':
  Duration: 01:02:03.50, start: 0.000000, bitrate: 1205 kb/s
At least one output file must be specified
"""


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [(_BANNER, 3723.5), ("  Duration: 00:00:09.00, start: 0", 9.0), ("Duration: N/A, bitrate: N/A", None), ("", None)],
)
def test_parse_duration(stderr, expected):
    assert parse_duration_s(stderr) == expected
