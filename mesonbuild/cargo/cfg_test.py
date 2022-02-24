from __future__ import annotations
import typing as T

import pytest

from .cfg import lexer, parse, TokenType
from . import builder
from . import cfg
from .. import mparser


@pytest.mark.parametrize(
    ['raw', 'expected'],
    [
        ('"unix"', [(TokenType.STRING, 'unix')]),
        ('unix', [(TokenType.IDENTIFIER, 'unix')]),
        ('not(unix)', [
            (TokenType.NOT, None),
            (TokenType.LPAREN, None),
            (TokenType.IDENTIFIER, 'unix'),
            (TokenType.RPAREN, None),
        ]),
        ('any(unix, windows)', [
            (TokenType.ANY, None),
            (TokenType.LPAREN, None),
            (TokenType.IDENTIFIER, 'unix'),
            (TokenType.COMMA, None),
            (TokenType.IDENTIFIER, 'windows'),
            (TokenType.RPAREN, None),
        ]),
        ('target_arch = "x86_64"', [
            (TokenType.IDENTIFIER, 'target_arch'),
            (TokenType.EQUAL, None),
            (TokenType.STRING, 'x86_64'),
        ]),
        ('all(target_arch = "x86_64", unix)', [
            (TokenType.ALL, None),
            (TokenType.LPAREN, None),
            (TokenType.IDENTIFIER, 'target_arch'),
            (TokenType.EQUAL, None),
            (TokenType.STRING, 'x86_64'),
            (TokenType.COMMA, None),
            (TokenType.IDENTIFIER, 'unix'),
            (TokenType.RPAREN, None),
        ]),
    ],
)
def test_lex(raw: str, expected: T.List[T.Tuple[TokenType, T.Optional[str]]]) -> None:
    got = list(lexer(raw))
    assert got == expected


@pytest.mark.parametrize(
    ['raw', 'expected'],
    [
        # ('windows', builder.equal(
        #     builder.method('cpu_family', builder.identifier('host_machine', '')),
        #     builder.string('windows', ''))
        # ),
        ('target_os = "windows"', cfg.Equal('', cfg.Identifier('', "target_os"), cfg.String('', "windows"))),
        ('target_arch = "x86"', cfg.Equal('', cfg.Identifier('', "target_arch"), cfg.String('', "x86"))),
        ('target_family = "unix"', cfg.Equal('', cfg.Identifier('', "target_family"), cfg.String('', "unix"))),
        ('any(target_arch = "x86", target_arch = "x86_64")',
            cfg.Any(
                '', [
                cfg.Equal('', cfg.Identifier('', "target_arch"), cfg.String('', "x86")),
                cfg.Equal('', cfg.Identifier('', "target_arch"), cfg.String('', "x86_64")),
            ])),
        ('all(target_arch = "x86", target_os = "linux")',
            cfg.All(
                '', [
                cfg.Equal('', cfg.Identifier('', "target_arch"), cfg.String('', "x86")),
                cfg.Equal('', cfg.Identifier('', "target_os"), cfg.String('', "linux")),
            ])),
        ('not(all(target_arch = "x86", target_os = "linux"))',
            cfg.Not(
                '',
                cfg.All(
                    '', [
                    cfg.Equal('', cfg.Identifier('', "target_arch"), cfg.String('', "x86")),
                    cfg.Equal('', cfg.Identifier('', "target_os"), cfg.String('', "linux")),
                ]))),
    ],
)
def test_parse(raw: str, expected: cfg.IR) -> None:
    got = parse(iter(lexer(raw)), '')
    assert got == expected


_HOST_MACHINE = builder.identifier('host_machine', '')


@pytest.mark.parametrize(
    ['raw', 'expected'],
    [
        # ('windows', builder.equal(
        #     builder.method('cpu_family', builder.identifier('host_machine', '')),
        #     builder.string('windows', ''))
        # ),
        ('target_os = "windows"',
         builder.equal(builder.method('system', _HOST_MACHINE),
                       builder.string('windows', ''))),
        ('target_arch = "x86"',
         builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                       builder.string('x86', ''))),
        ('target_family = "unix"',
         builder.equal(builder.method('system', _HOST_MACHINE),
                       builder.string('unix', ''))),
        ('not(target_arch = "x86")',
         builder.not_(builder.equal(
            builder.method('cpu_family', _HOST_MACHINE),
            builder.string('x86', '')), '')),
        ('any(target_arch = "x86", target_arch = "x86_64")',
         builder.or_(
            builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                          builder.string('x86', '')),
            builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                            builder.string('x86_64', '')))),
        ('any(target_arch = "x86", target_arch = "x86_64", target_arch = "aarch64")',
         builder.or_(
            builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                          builder.string('x86', '')),
            builder.or_(
                builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                              builder.string('x86_64', '')),
                builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                              builder.string('aarch64', ''))))),
        ('all(target_arch = "x86", target_arch = "x86_64")',
         builder.and_(
            builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                          builder.string('x86', '')),
            builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                            builder.string('x86_64', '')))),
        ('all(target_arch = "x86", target_arch = "x86_64", target_arch = "aarch64")',
         builder.and_(
            builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                          builder.string('x86', '')),
            builder.and_(
                builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                              builder.string('x86_64', '')),
                builder.equal(builder.method('cpu_family', _HOST_MACHINE),
                              builder.string('aarch64', ''))))),
    ],
)
def test_ir_to_meson(raw: str, expected: mparser.BaseNode) -> None:
    got = cfg.ir_to_meson(parse(iter(lexer(raw)), ''))
    assert got == expected
