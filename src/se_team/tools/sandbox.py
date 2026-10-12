"""
Sandboxed file system and test execution tools.
Restricted exclusively to the designated workspace directory.
Rejects any path that escapes it (including ../ and absolute paths).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field
from crewai.tools import BaseTool


class SandboxManager:
    """Manages sandboxed filesystem and test operations strictly within a base directory."""

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def validate_path(self, path: str | Path) -> Path:
        """
        Validates that a given path stays strictly inside the base directory.
        Raises ValueError if the path attempts to escape or points outside.
        """
        p = Path(path)
        # If absolute, resolve directly; if relative, resolve relative to base_dir
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (self.base_dir / p).resolve()

        # Check if resolved path is strictly within or equal to self.base_dir
        try:
            resolved.relative_to(self.base_dir)
        except ValueError:
            raise ValueError(
                f"Security violation: path '{path}' escapes workspace sandbox '{self.base_dir}'"
            )

        return resolved

    def write_file(self, file_path: str, content: str) -> str:
        """Writes content to a file inside the sandboxed workspace."""
        target = self.validate_path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        rel_path = target.relative_to(self.base_dir).as_posix()
        return f"File successfully written to: {rel_path} ({len(content)} characters)"

    def read_file(self, file_path: str) -> str:
        """Reads content from a file inside the sandboxed workspace."""
        target = self.validate_path(file_path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: '{file_path}'")
        if not target.is_file():
            raise ValueError(f"Path is not a regular file: '{file_path}'")
        return target.read_text(encoding="utf-8")

    def list_files(self, sub_directory: str = ".") -> List[str]:
        """Lists all files recursively under the given directory inside the workspace."""
        target = self.validate_path(sub_directory)
        if not target.exists():
            raise FileNotFoundError(f"Directory not found: '{sub_directory}'")
        if not target.is_dir():
            raise ValueError(f"Path is not a directory: '{sub_directory}'")

        file_list: List[str] = []
        for root, _, files in os.walk(target):
            for f in sorted(files):
                full = Path(root) / f
                file_list.append(full.relative_to(self.base_dir).as_posix())
        return file_list

    def run_tests(
        self,
        test_path: Optional[str] = None,
        test_code: Optional[str] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Executes pytest strictly inside the sandboxed workspace without arbitrary shell access.
        Optionally writes test_code to a test file before running.
        """
        if test_code:
            target_test_file = test_path or "tests/test_backend.py"
            self.write_file(target_test_file, test_code)
            test_path = target_test_file

        cmd = [sys.executable, "-m", "pytest", "-v", "--tb=short"]
        if test_path:
            validated_test = self.validate_path(test_path)
            cmd.append(str(validated_test))

        env = os.environ.copy()
        # Ensure backend package can be imported by pytest
        backend_dir = str((self.base_dir / "backend").resolve())
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{self.base_dir};{backend_dir};{existing_pythonpath}"
            if existing_pythonpath
            else f"{self.base_dir};{backend_dir}"
        )
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.base_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            passed = proc.returncode == 0
            return {
                "exit_code": proc.returncode,
                "passed": passed,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "output": proc.stdout + ("\nSTDERR:\n" + proc.stderr if proc.stderr else ""),
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "exit_code": -1,
                "passed": False,
                "stdout": exc.stdout or "",
                "stderr": f"Pytest execution timed out after {timeout} seconds",
                "output": f"ERROR: Pytest execution timed out after {timeout} seconds",
            }
        except Exception as exc:
            return {
                "exit_code": -1,
                "passed": False,
                "stdout": "",
                "stderr": str(exc),
                "output": f"ERROR: Failed to run pytest: {exc}",
            }


# --- Pydantic Tool Input Schemas ---

class ReadFileInput(BaseModel):
    file_path: str = Field(..., description="Relative path of the file to read inside the workspace.")

class WriteFileInput(BaseModel):
    file_path: str = Field(..., description="Relative path of the file to write inside the workspace.")
    content: str = Field(..., description="Full text/source code content to write.")

class ListFilesInput(BaseModel):
    sub_directory: str = Field(default=".", description="Relative subdirectory inside workspace to list (default: root '.').")

class RunTestsInput(BaseModel):
    test_path: Optional[str] = Field(default=None, description="Optional relative path to a specific test file or directory.")
    test_code: Optional[str] = Field(default=None, description="Optional pytest test code to write before running pytest.")


# --- CrewAI Tool Implementations ---

class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = (
        "Reads file content from the sandboxed workspace. Path must be within the workspace. "
        "Any attempt to escape using '../' or absolute paths outside the workspace is rejected."
    )
    args_schema: Type[BaseModel] = ReadFileInput
    sandbox: SandboxManager = Field(..., description="Sandbox manager instance")

    def _run(self, file_path: str) -> str:
        try:
            return self.sandbox.read_file(file_path)
        except Exception as exc:
            return f"Error reading file '{file_path}': {exc}"


class WriteFileTool(BaseTool):
    name: str = "write_file"
    description: str = (
        "Writes text/code content to a file inside the sandboxed workspace. "
        "Creates parent directories if necessary. Any attempt to escape the workspace is rejected."
    )
    args_schema: Type[BaseModel] = WriteFileInput
    sandbox: SandboxManager = Field(..., description="Sandbox manager instance")

    def _run(self, file_path: str, content: str) -> str:
        try:
            return self.sandbox.write_file(file_path, content)
        except Exception as exc:
            return f"Error writing file '{file_path}': {exc}"


class ListFilesTool(BaseTool):
    name: str = "list_files"
    description: str = (
        "Lists all files inside the sandboxed workspace or a subdirectory. "
        "Restricted to workspace paths only."
    )
    args_schema: Type[BaseModel] = ListFilesInput
    sandbox: SandboxManager = Field(..., description="Sandbox manager instance")

    def _run(self, sub_directory: str = ".") -> str:
        try:
            files = self.sandbox.list_files(sub_directory)
            if not files:
                return f"No files found in '{sub_directory}'."
            return "Files in workspace:\n" + "\n".join(f"- {f}" for f in files)
        except Exception as exc:
            return f"Error listing files in '{sub_directory}': {exc}"


class RunTestsTool(BaseTool):
    name: str = "run_tests"
    description: str = (
        "Runs pytest inside the sandboxed workspace with a timeout. "
        "Can execute existing tests or write new test code into the workspace and run it. "
        "No arbitrary shell access is permitted."
    )
    args_schema: Type[BaseModel] = RunTestsInput
    sandbox: SandboxManager = Field(..., description="Sandbox manager instance")

    def _run(self, test_path: Optional[str] = None, test_code: Optional[str] = None) -> str:
        try:
            result = self.sandbox.run_tests(test_path=test_path, test_code=test_code)
            status = "PASSED" if result["passed"] else "FAILED"
            return (
                f"=== Pytest Results: {status} (Exit Code: {result['exit_code']}) ===\n"
                f"{result['output']}"
            )
        except Exception as exc:
            return f"Error executing tests: {exc}"
