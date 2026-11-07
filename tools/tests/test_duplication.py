"""check_duplication on Python files ignores comments and docstrings but still sees real code."""
import pytest

from artifactory.checks.duplication import check_duplication

DUP = {"cfg": [r"os\.environ"], "http": [r"[\"']/healthz"]}


def scan(tmp_path, source, name="m.py"):
    f = tmp_path / name
    f.write_text(source)
    return check_duplication(tmp_path, [f], DUP)


@pytest.mark.parametrize("source", [
    "# uses os.environ\nx = 1\n",
    "x = 1  # os.environ here\n",
    '"""Module doc: os.environ\nsecond os.environ line\n"""\nx = 1\n',
    "def f():\n    '''os.environ'''\n    return 1\n",
    'def f():\n    """Multi-line\n    os.environ\n    """\n    return 1\n',
])
def test_prose_mentions_not_flagged(tmp_path, source):
    assert scan(tmp_path, source).passed


def test_real_environ_flagged_with_line_number(tmp_path):
    r = scan(tmp_path, '"""doc os.environ"""\n\nimport os\nx = os.environ["X"]\n')
    assert not r.passed and "m.py:4 matches cfg" in r.detail and "m.py:1" not in r.detail


def test_healthz_string_in_code_flagged(tmp_path):
    r = scan(tmp_path, 'def h(path):\n    if path == "/healthz":\n        return 1\n')
    assert not r.passed and "m.py:2 matches http" in r.detail


def test_string_after_docstring_line_number_stable(tmp_path):
    r = scan(tmp_path, 'def f():\n    """a\n    b\n    """\n    return os.environ\n')
    assert not r.passed and "m.py:5 matches cfg" in r.detail


def test_untokenizable_file_still_scanned(tmp_path):
    r = scan(tmp_path, 'x = (\n# os.environ\n"""unterminated\n')
    assert not r.passed and "matches cfg" in r.detail


def test_other_suffix_keeps_raw_matching(tmp_path):
    assert not scan(tmp_path, "// os.environ\n", name="a.go").passed
