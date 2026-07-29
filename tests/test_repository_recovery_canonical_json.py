from __future__ import annotations

import math

import pytest

from hqa.repository_recovery import canonical_json_bytes


def test_canonical_json_interface_emits_exact_compact_utf8_bytes() -> None:
    assert canonical_json_bytes({"z": "中文", "a": [2, 1]}) == (
        b'{"a":[2,1],"z":"\xe4\xb8\xad\xe6\x96\x87"}'
    )

    with pytest.raises(ValueError, match="JSON compliant"):
        canonical_json_bytes({"value": math.nan})
