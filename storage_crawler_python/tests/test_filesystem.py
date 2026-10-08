from pathlib import Path

from storage_crawler.config import CrawlerConfig
from storage_crawler.filesystem import run_scan


def test_recursive_scan_and_folder_aggregation(tmp_path: Path):
    root = tmp_path / "Reservoir Engineering"
    folder_a = root / "Field A" / "Model"
    folder_b = root / "Field B"
    folder_a.mkdir(parents=True)
    folder_b.mkdir(parents=True)

    (folder_a / "model.sim").write_bytes(b"x" * 1024)
    (folder_a / "results.rst").write_bytes(b"x" * 2048)
    (folder_b / "notes.txt").write_bytes(b"x" * 512)

    config = CrawlerConfig.from_values(
        root_folders=[str(root)],
        max_depth=5,
        skip_owner_info=True,
    )

    records = []
    summary = run_scan(config, records.append)

    assert summary.total_files == 3
    assert summary.total_folders == 3

    model_folder = next(
        r for r in records
        if r.item_type == "Folder"
        and Path(r.full_path).name == "Model"
        and Path(r.full_path).parent.name == "Field A"
    )

    expected_gb = 3072 / (1024 ** 3)
    assert abs(model_folder.size_gb - expected_gb) < 1e-15
    assert model_folder.file_count_in_folder == 2


def test_max_depth_is_enforced_during_traversal(tmp_path: Path):
    root = tmp_path / "Root"
    deep = root / "L1" / "L2" / "L3" / "L4"
    deep.mkdir(parents=True)
    (deep / "deep.sim").write_bytes(b"x")

    config = CrawlerConfig.from_values(
        root_folders=[str(root)],
        max_depth=2,
        skip_owner_info=True,
    )

    records = []
    run_scan(config, records.append)

    paths = {Path(r.full_path) for r in records}
    assert not any(path.name == "deep.sim" for path in paths)
    assert not any(path.name == "L3" for path in paths)

    # A root-level file is depth 1 and is therefore allowed.
    root_file = root / "root.sim"
    root_file.write_bytes(b"x")

    # A file inside L2 would be depth 3 and is therefore excluded.
    l2_file = root / "L1" / "L2" / "l2.sim"
    l2_file.write_bytes(b"x")

    records = []
    run_scan(config, records.append)

    names = {Path(r.full_path).name for r in records}
    assert "root.sim" in names
    assert "l2.sim" not in names


def test_output_file_is_not_scanned_while_being_written(tmp_path: Path):
    root = tmp_path / "Root"
    root.mkdir()
    (root / "data.sim").write_bytes(b"x")

    output = root / "STORAGE_ANALYSIS.csv"

    config = CrawlerConfig.from_values(
        root_folders=[str(root)],
        output_path=str(output),
        max_depth=5,
        skip_owner_info=True,
    )

    from storage_crawler.exporter import CsvExporter

    records = []
    with CsvExporter(output, config.hierarchy_levels) as exporter:
        run_scan(config, lambda record: (records.append(record), exporter.write(record)))

    assert not any(Path(r.full_path).name == output.name for r in records)
