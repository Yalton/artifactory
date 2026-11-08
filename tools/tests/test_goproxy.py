import os
import subprocess
import zipfile
from pathlib import Path

from artifactory.goproxy import build_goproxy

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "go"
MODS = sorted(p for p in SAMPLES.iterdir() if (p / "go.mod").is_file())


def go_env(proxy: Path, root: Path) -> dict:
    return {**os.environ, "GOPROXY": f"file://{proxy}", "GONOSUMDB": "repo.billbert.co/artifactory",
            "GOFLAGS": "-mod=mod", "GOMODCACHE": str(root / "modcache"), "GOPATH": str(root / "gopath")}


def test_proxy_serves_modules(tmp_path):
    proxy = tmp_path / "proxy"
    build_goproxy(MODS, proxy)
    app = tmp_path / "app"
    app.mkdir()
    (app / "go.mod").write_text("module app\n\ngo 1.24\n")
    r = subprocess.run(["go", "get", "repo.billbert.co/artifactory/kvstore@v0.2.0"], cwd=app,
                       env=go_env(proxy, tmp_path), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "repo.billbert.co/artifactory/kvstore v0.2.0" in (app / "go.mod").read_text()


def test_proxy_layout_and_zip_contents(tmp_path):
    build_goproxy(MODS, tmp_path)
    base = tmp_path / "repo.billbert.co" / "artifactory" / "kvstore" / "@v"
    assert (base / "list").read_text().split() == ["v0.2.0"]
    assert '"Version":"v0.2.0"' in (base / "v0.2.0.info").read_text().replace(" ", "")
    assert (base / "v0.2.0.mod").read_text().startswith("module repo.billbert.co/artifactory/kvstore")
    names = zipfile.ZipFile(base / "v0.2.0.zip").namelist()
    prefix = "repo.billbert.co/artifactory/kvstore@v0.2.0/"
    for f in ("go.mod", "README.md", "module.yaml", "kvstore.go", "example/main.go"):
        assert prefix + f in names
    assert all(n.startswith(prefix) for n in names)


def test_zip_excludes_vendor_and_nested_modules(tmp_path):
    src = tmp_path / "src" / "m"
    (src / "vendor" / "x").mkdir(parents=True)
    (src / "vendor" / "x" / "x.go").write_text("package x\n")
    (src / "nested").mkdir()
    (src / "nested" / "go.mod").write_text("module nested\n")
    (src / "nested" / "n.go").write_text("package nested\n")
    (src / "go.mod").write_text("module repo.billbert.co/artifactory/m\n\ngo 1.24\n")
    (src / "m.go").write_text("package m\n")
    (src / "module.yaml").write_text("version: 0.1.0\n")
    out = tmp_path / "out"
    build_goproxy([src], out)
    names = zipfile.ZipFile(out / "repo.billbert.co/artifactory/m/@v/v0.1.0.zip").namelist()
    assert sorted(n.split("@v0.1.0/")[1] for n in names) == ["go.mod", "m.go", "module.yaml"]
