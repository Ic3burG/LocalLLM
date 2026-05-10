import pytest
import time
from agent_utils import TelemetryManager

def test_telemetry_manager_singleton():
    tm1 = TelemetryManager()
    tm2 = TelemetryManager()
    assert tm1 is tm2

def test_telemetry_manager_initial_state():
    tm = TelemetryManager()
    # Reset state for test isolation since it's a singleton
    tm.reset()
    stats = tm.get_stats()
    assert stats["total_tasks"] == 0
    assert stats["success_count"] == 0
    assert stats["error_count"] == 0
    assert stats["tool_counts"] == {}
    assert stats["recent_tasks"] == []

def test_telemetry_manager_record_start():
    tm = TelemetryManager()
    tm.reset()
    tm.record_start("task-1")
    stats = tm.get_stats()
    assert stats["total_tasks"] == 1

def test_telemetry_manager_record_tool_use():
    tm = TelemetryManager()
    tm.reset()
    tm.record_tool_use("read_file")
    tm.record_tool_use("read_file")
    tm.record_tool_use("write_file")
    stats = tm.get_stats()
    assert stats["tool_counts"] == {"read_file": 2, "write_file": 1}

def test_telemetry_manager_record_completion_success():
    tm = TelemetryManager()
    tm.reset()
    tm.record_start("task-1")
    time.sleep(0.01)
    tm.record_complete("task-1", "success")
    stats = tm.get_stats()
    assert stats["success_count"] == 1
    assert stats["error_count"] == 0
    assert len(stats["recent_tasks"]) == 1
    assert stats["recent_tasks"][0]["id"] == "task-1"
    assert stats["recent_tasks"][0]["status"] == "success"
    assert stats["recent_tasks"][0]["duration_ms"] >= 10

def test_telemetry_manager_record_completion_error():
    tm = TelemetryManager()
    tm.reset()
    tm.record_start("task-2")
    tm.record_complete("task-2", "error")
    stats = tm.get_stats()
    assert stats["success_count"] == 0
    assert stats["error_count"] == 1
    assert len(stats["recent_tasks"]) == 1
    assert stats["recent_tasks"][0]["id"] == "task-2"
    assert stats["recent_tasks"][0]["status"] == "error"

def test_telemetry_manager_recent_tasks_limit():
    tm = TelemetryManager()
    tm.reset()
    for i in range(10):
        task_id = f"task-{i}"
        tm.record_start(task_id)
        tm.record_complete(task_id, "success")
    
    stats = tm.get_stats()
    assert len(stats["recent_tasks"]) == 5
    # Should be the last 5 tasks
    assert stats["recent_tasks"][0]["id"] == "task-9"
    assert stats["recent_tasks"][4]["id"] == "task-5"

def test_telemetry_manager_success_rate():
    tm = TelemetryManager()
    tm.reset()
    
    # Start 3 tasks
    tm.record_start("task-1")
    tm.record_start("task-2")
    tm.record_start("task-3")
    
    # 1 success, 1 error, 1 in progress
    tm.record_complete("task-1", "success")
    tm.record_complete("task-2", "error")
    
    stats = tm.get_stats()
    assert stats["total_tasks"] == 3
    assert stats["success_count"] == 1
    assert stats["error_count"] == 1
    # Denominator should be success_count + error_count = 2
    # success_rate = 1 / 2 = 0.5
    assert stats["success_rate"] == 0.5

    # Complete the third task as success
    tm.record_complete("task-3", "success")
    stats = tm.get_stats()
    # success_rate = 2 / 3 = 0.666...
    assert stats["success_rate"] == pytest.approx(0.6666666666666666)
