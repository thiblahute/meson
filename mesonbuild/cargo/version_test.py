
from __future__ import annotations
import typing as T

import pytest

from .version import convert


@pytest.mark.parametrize(
    ['raw', 'expected'],
    [
        # Basic requirements
        ('>= 1', ['>= 1']),
        ('> 1', ['> 1']),
        ('= 1', ['= 1']),
        ('< 1', ['< 1']),
        ('<= 1', ['<= 1']),
        ('2', ['>= 2', '< 3']),
        ('2.4', ['>= 2.4', '< 3']),
        ('2.4.5', ['>= 2.4.5', '< 3']),

        # Carrot tests
        ('~1', ['>= 1', '< 2']),
        ('~1.1', ['>= 1.1', '< 1.2']),
        ('~1.1.2', ['>= 1.1.2', '< 1.2.0']),

        # Wildcards
        ('*', []),
        ('1.*', ['>= 1', '< 2']),
        ('2.3.*', ['>= 2.3', '< 2.4']),

        # Unqualified
        ('1', ['>= 1', '< 2']),
        ('4.1', ['>= 4.1', '< 5']),
        ('2.4', ['>= 2.4', '< 3']),

        # Caret
        ('^1.2.4', ['== 1.2.4']),

        # Multiple requirements
        ('>= 1.2.3, < 1.4.7', ['>= 1.2.3', '< 1.4.7']),
    ]
)
def test_ir_to_meson(raw: str, expected: T.List[str]) -> None:
    assert convert(raw) == expected
