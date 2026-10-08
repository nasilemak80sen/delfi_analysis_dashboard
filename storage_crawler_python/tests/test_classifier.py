from storage_crawler.classifier import (
    get_file_category,
    is_simulation_file,
)


def test_known_simulation_extensions():
    assert get_file_category(".sim") == "Simulation Model"
    assert get_file_category(".RST") == "Simulation Output"
    assert is_simulation_file(".grdecl") == "Yes"


def test_known_non_simulation_extensions():
    assert get_file_category(".xlsx") == "Spreadsheet"
    assert get_file_category(".PDF") == "Document"
    assert is_simulation_file(".zip") == "No"


def test_unknown_extension():
    assert get_file_category(".madeup") == "Other"
