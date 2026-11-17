"""Shared synthetic meshes. All sizes are millimetres."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh


def save(mesh: trimesh.Trimesh, folder: Path, name: str) -> Path:
    """Write a mesh to folder/name (the extension picks the format) and return the path."""
    path = Path(folder) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)
    return path


@pytest.fixture
def cube() -> trimesh.Trimesh:
    """Closed 20 mm cube centred on the origin."""
    return trimesh.creation.box(extents=(20, 20, 20))


@pytest.fixture
def open_cube(cube: trimesh.Trimesh) -> trimesh.Trimesh:
    """The cube with two triangles removed, so it is not watertight."""
    return trimesh.Trimesh(vertices=cube.vertices, faces=cube.faces[:-2], process=False)


@pytest.fixture
def big_box() -> trimesh.Trimesh:
    """300 mm box: too large for the 220 x 220 x 250 mm bed in any orientation."""
    return trimesh.creation.box(extents=(300, 300, 300))


@pytest.fixture
def link() -> trimesh.Trimesh:
    """One chain link: a torus in the XY plane, 20 mm centre-line radius, 4 mm wire radius."""
    return trimesh.creation.torus(major_radius=20, minor_radius=4)


@pytest.fixture
def link_pair(link: trimesh.Trimesh) -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
    """Two interlocked links that do not touch: the second is turned 90 degrees and shifted 20 mm."""
    second = link.copy()
    second.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    second.apply_translation((20, 0, 0))
    return link, second


@pytest.fixture
def save_mesh():
    return save
