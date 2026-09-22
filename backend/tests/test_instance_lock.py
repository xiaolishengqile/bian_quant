import pytest
from backend.instance_lock import InstanceLock


def test_second_worker_cannot_trade_the_same_database(tmp_path):
    first = InstanceLock(tmp_path / "quant.db.lock")
    second = InstanceLock(tmp_path / "quant.db.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="正在运行"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()
