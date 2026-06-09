import json

from cous.logger import EventLogger


def test_rotation_creates_backup_files(tmp_path):
    logger = EventLogger(tmp_path / "events.jsonl", max_bytes=100, backup_count=2)

    logger.log("test", data="x" * 200)
    logger.log("test", data="y" * 200)
    logger.log("test", data="z" * 200)

    assert (tmp_path / "events.jsonl.1").is_file()
    assert (tmp_path / "events.jsonl.2").is_file()
    assert not (tmp_path / "events.jsonl.3").exists()


def test_rotation_preserves_most_recent_log(tmp_path):
    logger = EventLogger(tmp_path / "events.jsonl", max_bytes=80, backup_count=2)

    logger.log("first", msg="a" * 100)
    logger.log("second", msg="b" * 100)

    current = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").strip())
    previous = json.loads((tmp_path / "events.jsonl.1").read_text(encoding="utf-8").strip())

    assert current["event"] == "second"
    assert previous["event"] == "first"
