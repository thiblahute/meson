# SPDX-License-Identifier: Apache-2.0
# Copyright © 2022 Intel Corporation

"""Convert Cargo versions into Meson compatible ones."""

from __future__ import annotations
import typing as T


def convert(cargo_ver: str) -> T.List[str]:
    """Convert a Cargo compatible version into a Meson compatible one.

    :param cargo_ver: The version, as Cargo specifies
    :return: A list of version constraints, as Meson understands them
    """
    # Cleanup, just for safety
    cargo_ver = cargo_ver.strip()
    cargo_vers = [c.strip() for c in cargo_ver.split(',')]

    out: T.List[str] = []

    for ver in cargo_vers:
        # This covers >= and =< as well
        # https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#comparison-requirements
        if ver.startswith(('>', '<', '=')):
            out.append(ver)

        elif ver.startswith('~'):
            # Rust has these tilde requirements, which means that it is >= to
            # the version, but less than the nxt version
            # https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#tilde-requirements
            # we convert those into a pair of constraints
            v = ver[1:].split('.')
            out.append(f'>= {".".join(v)}')
            if len(v) == 3:
                out.append(f'< {v[0]}.{int(v[1]) + 1}.0')
            elif len(v) == 2:
                out.append(f'< {v[0]}.{int(v[1]) + 1}')
            else:
                out.append(f'< {int(v[0]) + 1}')

        elif ver.startswith('^'):
            # https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#caret-requirements
            out.append(f'== {ver[1:]}')

        elif '*' in ver:
            # Rust has astrisk requirements,, which are like 1.* == ~1
            # https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#wildcard-requirements
            v = ver.split('.')[:-1]
            if v:
                out.append(f'>= {".".join(v)}')
            if len(v) == 2:
                out.append(f'< {v[0]}.{int(v[1]) + 1}')
            elif len(v) == 1:
                out.append(f'< {int(v[0]) + 1}')

        else:
            # If there is no qualifier, then it means this or the next major version
            # https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#specifying-dependencies-from-cratesio
            out.extend([f'>= {ver}', f'< {int(ver.split(".", maxsplit=1)[0]) + 1}'])


    return out
