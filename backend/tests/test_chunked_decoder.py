from io import BytesIO
from types import SimpleNamespace

from interfaces.channels.qq import _read_chunked


def test_read_chunked_decodes_body():
    # Simulate chunked transfer stream:
    # 4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n
    stream = BytesIO(b"4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n")
    fake = SimpleNamespace(rfile=stream)
    assert _read_chunked(fake) == b"Wikipedia"
