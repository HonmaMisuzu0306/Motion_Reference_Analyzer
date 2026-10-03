import hashlib
import sqlite3

import pytest

from app.runtime_paths import RuntimePaths
from db.schema import init_schema


def test_import_preserves_ids_assets_and_readonly_source(tmp_path):
    from projects.legacy_import import import_legacy_library

    source = tmp_path / "旧库"
    (source / "output/p/shots").mkdir(parents=True)
    image = source / "output/p/shots/frame.jpg"
    image.write_bytes(b"frame")
    database = source / "output/mra_library.db"
    conn = sqlite3.connect(database)
    init_schema(conn)
    conn.execute(
        "INSERT INTO projects(id,name,assets_dir,video_path) VALUES(7,'p','output/p','missing.mp4')"
    )
    conn.execute(
        "INSERT INTO shots(id,project_id,shot_id,frame_paths,thumbnail_path) VALUES(9,7,'s','[\"output/p/shots/frame.jpg\"]','output/p/shots/frame.jpg')"
    )
    conn.execute("INSERT INTO tags(id,name) VALUES(3,'保留')")
    conn.execute("INSERT INTO shot_tags VALUES(9,3)")
    conn.commit()
    conn.close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    target = RuntimePaths(tmp_path / "新库", source)
    result = import_legacy_library(database, source, target)
    assert result["projects"] == 1
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    conn = sqlite3.connect(target.database)
    assert conn.execute("SELECT * FROM shot_tags").fetchone() == (9, 3)
    asset = conn.execute("SELECT thumbnail_path FROM shots WHERE id=9").fetchone()[0]
    assert (target.data_root / asset.removeprefix("@data/")).read_bytes() == b"frame"
    conn.close()
    with pytest.raises(ValueError, match="为空"):
        import_legacy_library(database, source, target)


def test_outside_asset_rejected_without_partial_import(tmp_path):
    from projects.legacy_import import import_legacy_library

    source = tmp_path / "old"
    source.mkdir()
    database = source / "old.db"
    conn = sqlite3.connect(database)
    init_schema(conn)
    conn.execute("INSERT INTO projects(name,assets_dir) VALUES('bad',?)", (str(tmp_path),))
    conn.commit()
    conn.close()
    target = RuntimePaths(tmp_path / "target", source)
    with pytest.raises(ValueError, match="源根"):
        import_legacy_library(database, source, target)
    conn = sqlite3.connect(target.database)
    assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["missing_frame", "copy_error"])
def test_import_failure_keeps_empty_target_and_cleans_staging(tmp_path, monkeypatch, failure):
    from projects import legacy_import

    source = tmp_path / "旧目录"
    assets = source / "output/p"
    assets.mkdir(parents=True)
    database = source / "output/old.db"
    with sqlite3.connect(database) as conn:
        init_schema(conn)
        conn.execute("INSERT INTO projects(id,name,assets_dir) VALUES(7,'p','output/p')")
        conn.execute(
            "INSERT INTO shots(project_id,shot_id,frame_paths) VALUES(7,'s','[\"output/p/missing.jpg\"]')"
        )
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    if failure == "copy_error":

        def fail_copy(*args, **kwargs):
            raise OSError("disk failure")

        monkeypatch.setattr(legacy_import.shutil, "copytree", fail_copy)
    target = RuntimePaths(tmp_path / "新目录", source)
    with pytest.raises((ValueError, OSError)):
        legacy_import.import_legacy_library(database, source, target)
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with sqlite3.connect(target.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM shots").fetchone()[0] == 0
    assert not list(target.data_root.glob(".mra-import-*"))
    assert not list(target.data_root.glob("imported-*"))
