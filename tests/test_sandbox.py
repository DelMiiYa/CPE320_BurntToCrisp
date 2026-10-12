"""
Tests for sandbox path-restriction logic and execution tools.
Verifies that all operations are strictly confined to the workspace and reject directory traversal.
"""

import sys
import tempfile
from pathlib import Path
import pytest

from se_team.tools.sandbox import (
    SandboxManager,
    ReadFileTool,
    WriteFileTool,
    ListFilesTool,
    RunTestsTool,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


def test_sandbox_write_and_read_inside_workspace(temp_workspace):
    sandbox = SandboxManager(temp_workspace)
    
    # Write inside workspace
    res = sandbox.write_file("sub/folder/hello.txt", "Hello World!")
    assert "successfully written" in res.lower()
    
    # Read back
    content = sandbox.read_file("sub/folder/hello.txt")
    assert content == "Hello World!"


def test_sandbox_rejects_parent_directory_traversal_write(temp_workspace):
    sandbox = SandboxManager(temp_workspace)
    
    with pytest.raises(ValueError, match="Security violation.*escapes workspace"):
        sandbox.write_file("../outside.txt", "malicious payload")

    with pytest.raises(ValueError, match="Security violation.*escapes workspace"):
        sandbox.write_file("foo/../../escaped.txt", "malicious payload")


def test_sandbox_rejects_parent_directory_traversal_read(temp_workspace):
    sandbox = SandboxManager(temp_workspace)
    
    with pytest.raises(ValueError, match="Security violation.*escapes workspace"):
        sandbox.read_file("../secret.txt")

    with pytest.raises(ValueError, match="Security violation.*escapes workspace"):
        sandbox.read_file("subdir/../../secret.txt")


def test_sandbox_rejects_absolute_path_outside_workspace(temp_workspace):
    sandbox = SandboxManager(temp_workspace)
    outside_dir = temp_workspace.parent / "completely_outside.txt"
    
    with pytest.raises(ValueError, match="Security violation.*escapes workspace"):
        sandbox.write_file(str(outside_dir), "outside content")

    with pytest.raises(ValueError, match="Security violation.*escapes workspace"):
        sandbox.read_file(str(outside_dir))


def test_sandbox_list_files(temp_workspace):
    sandbox = SandboxManager(temp_workspace)
    sandbox.write_file("file1.txt", "content1")
    sandbox.write_file("nested/file2.txt", "content2")

    files = sandbox.list_files(".")
    assert "file1.txt" in files
    assert "nested/file2.txt" in files

    # Reject listing outside
    with pytest.raises(ValueError, match="Security violation.*escapes workspace"):
        sandbox.list_files("../")


def test_sandbox_run_tests_success(temp_workspace):
    sandbox = SandboxManager(temp_workspace)
    test_code = """
def test_addition():
    assert 1 + 1 == 2
"""
    result = sandbox.run_tests(test_code=test_code)
    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert "1 passed" in result["stdout"]


def test_sandbox_run_tests_failure(temp_workspace):
    sandbox = SandboxManager(temp_workspace)
    test_code = """
def test_failure():
    assert 1 == 2
"""
    result = sandbox.run_tests(test_code=test_code)
    assert result["passed"] is False
    assert result["exit_code"] != 0
    assert "1 failed" in result["stdout"]


def test_sandbox_run_tests_rejects_outside_path(temp_workspace):
    sandbox = SandboxManager(temp_workspace)
    with pytest.raises(ValueError, match="Security violation.*escapes workspace"):
        sandbox.run_tests(test_path="../outside_test.py")


def test_crewai_tool_wrappers_reject_traversal(temp_workspace):
    sandbox = SandboxManager(temp_workspace)
    write_tool = WriteFileTool(sandbox=sandbox)
    read_tool = ReadFileTool(sandbox=sandbox)
    list_tool = ListFilesTool(sandbox=sandbox)
    test_tool = RunTestsTool(sandbox=sandbox)

    # Calling write with escaping path returns error string instead of crashing
    w_res = write_tool.run(file_path="../bad.txt", content="hack")
    assert "Security violation" in w_res

    r_res = read_tool.run(file_path="../bad.txt")
    assert "Security violation" in r_res

    l_res = list_tool.run(sub_directory="../")
    assert "Security violation" in l_res

    t_res = test_tool.run(test_path="../bad_test.py")
    assert "Security violation" in t_res
