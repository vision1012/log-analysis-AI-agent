"""
Unit test to verify JobStatus enum usage doesn't cause AttributeError.

Tests that:
1. JobStatus enum can be imported and used correctly
2. JobStatus.SUCCEEDED.value returns "succeeded"
3. JobStatus enum can be used in runner.py without exceptions
"""

from api.schemas.job import JobStatus


def test_job_status_enum_values():
    """Test that JobStatus enum has correct values."""
    assert JobStatus.QUEUED.value == "queued"
    assert JobStatus.RUNNING.value == "running"
    assert JobStatus.SUCCEEDED.value == "succeeded"
    assert JobStatus.FAILED.value == "failed"
    assert JobStatus.CANCELLED.value == "cancelled"
    print("✅ All enum values are correct")


def test_job_status_enum_usage():
    """Test that JobStatus enum can be used without AttributeError."""
    # This should not raise AttributeError
    status_value = JobStatus.SUCCEEDED.value
    assert isinstance(status_value, str)
    assert status_value == "succeeded"
    
    # Test that we can use it in comparisons
    assert JobStatus.SUCCEEDED.value == "succeeded"
    assert JobStatus.FAILED.value == "failed"
    print("✅ JobStatus enum can be used without AttributeError")


def test_job_status_enum_in_dict():
    """Test that JobStatus enum values work in dictionaries."""
    status_dict = {
        "status": JobStatus.SUCCEEDED.value,
        "other_field": "test"
    }
    assert status_dict["status"] == "succeeded"
    assert isinstance(status_dict["status"], str)
    print("✅ JobStatus enum values work in dictionaries")


def test_job_status_enum_import():
    """Test that JobStatus can be imported from api.schemas.job."""
    from api.schemas.job import JobStatus as ImportedJobStatus
    assert ImportedJobStatus.SUCCEEDED.value == "succeeded"
    assert ImportedJobStatus.FAILED.value == "failed"
    print("✅ JobStatus can be imported correctly")


def test_runner_imports():
    """Test that runner.py can import and use JobStatus."""
    try:
        from api.services.runner import JobRunner
        from api.schemas.job import JobStatus
        # Verify we can access the enum
        assert JobStatus.SUCCEEDED.value == "succeeded"
        assert JobStatus.FAILED.value == "failed"
        print("✅ Runner can import and use JobStatus enum")
    except AttributeError as e:
        print(f"❌ AttributeError: {e}")
        raise
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        raise


if __name__ == "__main__":
    print("Running JobStatus enum tests...")
    print("")
    test_job_status_enum_values()
    test_job_status_enum_usage()
    test_job_status_enum_in_dict()
    test_job_status_enum_import()
    test_runner_imports()
    print("")
    print("✅ All tests passed!")
