from __future__ import annotations

SIMULATION_EXTENSIONS = {
    ".ptd",
    ".sim",
    ".zgy",
    ".grdecl",
    ".dat",
    ".inc",
    ".rpt",
    ".prt",
    ".smspec",
    ".unsmry",
    ".grid",
    ".init",
    ".rft",
    ".rst",
}

FILE_CATEGORIES = {
    ".ptd": "Petrel Project",
    ".sim": "Simulation Model",
    ".zgy": "ZGY Seismic",
    ".dat": "Simulation Input",
    ".inc": "Simulation Input",
    ".grdecl": "Simulation Input",
    ".rpt": "Simulation Report",
    ".prt": "Simulation Report",
    ".smspec": "Simulation Output",
    ".unsmry": "Simulation Output",
    ".grid": "Simulation Output",
    ".init": "Simulation Output",
    ".rft": "Simulation Output",
    ".rst": "Simulation Output",
    ".xlsx": "Spreadsheet",
    ".xls": "Spreadsheet",
    ".csv": "Spreadsheet",
    ".pdf": "Document",
    ".docx": "Document",
    ".doc": "Document",
    ".pptx": "Document",
    ".ppt": "Document",
    ".jpg": "Image",
    ".jpeg": "Image",
    ".png": "Image",
    ".bmp": "Image",
    ".tif": "Image",
    ".tiff": "Image",
    ".txt": "Text/Log",
    ".log": "Text/Log",
    ".las": "Well Log Data",
    ".dev": "Well Log Data",
    ".dlis": "Well Log Data",
    ".lis": "Well Log Data",
    ".segy": "Seismic Data",
    ".sgy": "Seismic Data",
    ".seg": "Seismic Data",
}


def normalize_extension(extension: str | None) -> str:
    if not extension:
        return ""
    value = extension.strip().lower()
    return value if value.startswith(".") else f".{value}"


def get_file_category(extension: str | None) -> str:
    return FILE_CATEGORIES.get(normalize_extension(extension), "Other")


def is_simulation_file(extension: str | None) -> str:
    return "Yes" if normalize_extension(extension) in SIMULATION_EXTENSIONS else "No"
