from pathlib import Path

from storage_crawler.hierarchy import (
    depth_from_hierarchy,
    parent_path,
    relative_parts,
)


def test_relative_parts(tmp_path: Path):
    root = tmp_path / "Data"
    item = root / "FieldA" / "Model" / "model.sim"
    item.parent.mkdir(parents=True)
    item.write_bytes(b"x")

    assert relative_parts(root, item) == (
        "FieldA",
        "Model",
        "model.sim",
    )


def test_depth():
    assert depth_from_hierarchy(("A", "B", "C")) == 3


def test_parent_path(tmp_path: Path):
    item = tmp_path / "Data" / "FieldA"
    assert parent_path(item).name == "Data"
