from loader.load_snowflake import rows_loaded

DESC = [("file",), ("status",), ("rows_parsed",), ("rows_loaded",), ("error_limit",)]


def test_sums_rows_loaded_over_files():
    result = [("a.parquet", "LOADED", 10, 10, 1), ("b.parquet", "LOADED", 5, 5, 1)]
    assert rows_loaded(DESC, result) == 15


def test_no_files_processed():
    assert rows_loaded([("status",)], [("Copy executed with 0 files processed.",)]) == 0
