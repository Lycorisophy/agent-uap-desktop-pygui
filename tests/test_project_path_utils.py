"""项目相对路径规范化。"""

from uap.react.project_path_utils import normalize_relative_path_for_project


def test_strip_duplicate_project_folder_prefix() -> None:
    root = r"C:\Users\x\.uap\projects\e53a930f23424011a24f57556a433f99"
    assert (
        normalize_relative_path_for_project(
            r"e53a930f23424011a24f57556a433f99\data",
            root,
        )
        == "data"
    )


def test_strip_duplicate_twice_if_model_doubles() -> None:
    pid = "e53a930f23424011a24f57556a433f99"
    root = rf"C:\u\.uap\projects\{pid}"
    assert normalize_relative_path_for_project(f"{pid}/{pid}/data", root) == "data"


def test_plain_data_unchanged() -> None:
    root = r"C:\u\.uap\projects\abc"
    assert normalize_relative_path_for_project("data", root) == "data"


def test_absolute_unchanged() -> None:
    root = r"C:\u\.uap\projects\abc"
    assert normalize_relative_path_for_project(r"C:\other\file.txt", root) == r"C:\other\file.txt"
