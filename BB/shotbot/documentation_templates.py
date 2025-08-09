"""Documentation templates and standards for the ShotBot application.

This module provides standardized documentation templates, patterns, and utilities
for maintaining consistent, high-quality documentation throughout the codebase.
"""

import ast
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# Module Documentation Template
# ============================================================================

MODULE_TEMPLATE = '''"""%(brief_description)s

%(detailed_description)s

Architecture:
    %(architecture_notes)s

Key Components:
    %(components)s

Dependencies:
    %(dependencies)s

Example:
    %(example_code)s

See Also:
    %(see_also)s

Note:
    %(notes)s

Since: v%(version)s
"""
'''


# ============================================================================
# Class Documentation Template
# ============================================================================

CLASS_TEMPLATE = '''"""%(brief_description)s

%(detailed_description)s

This class provides:
    %(features)s

Attributes:
    %(attributes)s

Signals:
    %(signals)s

Thread Safety:
    %(thread_safety)s

Example:
    >>> %(example_usage)s

See Also:
    %(see_also)s
"""
'''


# ============================================================================
# Method Documentation Template
# ============================================================================

METHOD_TEMPLATE = '''"""%(brief_description)s

%(detailed_description)s

Args:
    %(args)s

Returns:
    %(returns)s

Raises:
    %(raises)s

Example:
    >>> %(example)s

Note:
    %(note)s

Since: v%(version)s
"""
'''


# ============================================================================
# API Documentation Patterns
# ============================================================================


@dataclass
class APIDocumentation:
    """Structured API documentation."""

    endpoint: str
    method: str
    description: str
    parameters: List[Tuple[str, str, bool]]  # name, type, required
    returns: str
    errors: List[Tuple[int, str]]  # code, description
    example: str
    rate_limit: Optional[str] = None
    authentication: Optional[str] = None
    deprecated: Optional[str] = None

    def to_markdown(self) -> str:
        """Convert to Markdown format."""
        lines = [
            f"## {self.endpoint}",
            f"**Method:** `{self.method}`",
            "",
            f"**Description:** {self.description}",
            "",
        ]

        if self.authentication:
            lines.extend(
                [
                    "**Authentication:** " + self.authentication,
                    "",
                ]
            )

        if self.deprecated:
            lines.extend(
                [
                    f"⚠️ **Deprecated:** {self.deprecated}",
                    "",
                ]
            )

        if self.parameters:
            lines.extend(
                [
                    "### Parameters",
                    "",
                    "| Name | Type | Required | Description |",
                    "|------|------|----------|-------------|",
                ]
            )
            for name, type_str, required in self.parameters:
                req = "Yes" if required else "No"
                lines.append(f"| `{name}` | {type_str} | {req} | |")
            lines.append("")

        lines.extend(
            [
                "### Returns",
                "",
                self.returns,
                "",
            ]
        )

        if self.errors:
            lines.extend(
                [
                    "### Errors",
                    "",
                    "| Code | Description |",
                    "|------|-------------|",
                ]
            )
            for code, desc in self.errors:
                lines.append(f"| {code} | {desc} |")
            lines.append("")

        if self.rate_limit:
            lines.extend(
                [
                    "### Rate Limiting",
                    "",
                    self.rate_limit,
                    "",
                ]
            )

        if self.example:
            lines.extend(
                [
                    "### Example",
                    "",
                    "```python",
                    self.example,
                    "```",
                    "",
                ]
            )

        return "\n".join(lines)


# ============================================================================
# Code Example Templates
# ============================================================================


class ExampleGenerator:
    """Generate standardized code examples."""

    @staticmethod
    def basic_usage(class_name: str, methods: List[str]) -> str:
        """Generate basic usage example.

        Args:
            class_name: Name of the class
            methods: List of method names to demonstrate

        Returns:
            Formatted example code
        """
        lines = [
            f"# Basic usage of {class_name}",
            f"instance = {class_name}()",
            "",
        ]

        for method in methods:
            lines.append(f"# Call {method}")
            lines.append(f"result = instance.{method}()")
            lines.append("print(result)")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def async_usage(class_name: str, signal_name: str) -> str:
        """Generate async/signal usage example.

        Args:
            class_name: Name of the class
            signal_name: Name of the signal

        Returns:
            Formatted example code
        """
        return f"""# Async usage with signals
instance = {class_name}()

# Connect to signal
def handle_{signal_name}(data):
    print(f"Received: {{data}}")

instance.{signal_name}.connect(handle_{signal_name})

# Start async operation
instance.start()

# Wait for completion
app.exec()
"""

    @staticmethod
    def error_handling(class_name: str, method_name: str) -> str:
        """Generate error handling example.

        Args:
            class_name: Name of the class
            method_name: Name of the method

        Returns:
            Formatted example code
        """
        return f"""# Error handling example
instance = {class_name}()

try:
    result = instance.{method_name}()
    print(f"Success: {{result}}")
except ValueError as e:
    print(f"Value error: {{e}}")
except Exception as e:
    print(f"Unexpected error: {{e}}")
finally:
    instance.cleanup()
"""


# ============================================================================
# Testing Documentation Templates
# ============================================================================

TEST_CLASS_TEMPLATE = '''"""Test suite for %(module_name)s.

This test suite covers:
    %(coverage_areas)s

Test Categories:
    - Unit Tests: %(unit_test_count)s
    - Integration Tests: %(integration_test_count)s
    - Performance Tests: %(performance_test_count)s

Fixtures:
    %(fixtures)s

Test Data:
    %(test_data)s

Note:
    %(notes)s
"""
'''

TEST_METHOD_TEMPLATE = '''"""Test %(test_aspect)s.

Given:
    %(given_context)s

When:
    %(when_action)s

Then:
    %(then_expectation)s

Test Data:
    %(test_data)s

Related Issues:
    %(issues)s
"""
'''


# ============================================================================
# Documentation Utilities
# ============================================================================


class DocStringParser:
    """Parse and validate docstrings."""

    @staticmethod
    def parse_google_style(docstring: str) -> Dict[str, Any]:
        """Parse Google-style docstring.

        Args:
            docstring: Docstring to parse

        Returns:
            Parsed sections
        """
        if not docstring:
            return {}

        sections = {
            "description": "",
            "args": {},
            "returns": "",
            "raises": {},
            "example": "",
            "note": "",
        }

        current_section = "description"
        current_lines = []

        for line in docstring.split("\n"):
            line = line.strip()

            # Check for section headers
            if line in ("Args:", "Arguments:", "Parameters:"):
                sections["description"] = "\n".join(current_lines).strip()
                current_section = "args"
                current_lines = []
            elif line in ("Returns:", "Return:"):
                if current_section == "args":
                    sections["args"] = DocStringParser._parse_args(current_lines)
                current_section = "returns"
                current_lines = []
            elif line in ("Raises:", "Raise:"):
                if current_section == "returns":
                    sections["returns"] = "\n".join(current_lines).strip()
                current_section = "raises"
                current_lines = []
            elif line in ("Example:", "Examples:"):
                if current_section == "raises":
                    sections["raises"] = DocStringParser._parse_raises(current_lines)
                current_section = "example"
                current_lines = []
            elif line in ("Note:", "Notes:"):
                if current_section == "example":
                    sections["example"] = "\n".join(current_lines).strip()
                current_section = "note"
                current_lines = []
            else:
                if line:  # Skip empty lines
                    current_lines.append(line)

        # Handle last section
        if current_section == "description":
            sections["description"] = "\n".join(current_lines).strip()
        elif current_section == "args":
            sections["args"] = DocStringParser._parse_args(current_lines)
        elif current_section == "returns":
            sections["returns"] = "\n".join(current_lines).strip()
        elif current_section == "raises":
            sections["raises"] = DocStringParser._parse_raises(current_lines)
        elif current_section == "example":
            sections["example"] = "\n".join(current_lines).strip()
        elif current_section == "note":
            sections["note"] = "\n".join(current_lines).strip()

        return sections

    @staticmethod
    def _parse_args(lines: List[str]) -> Dict[str, str]:
        """Parse argument descriptions."""
        args = {}
        current_arg = None
        current_desc = []

        for line in lines:
            # Check if it's an arg definition (name: description)
            if ":" in line and not line.startswith(" "):
                if current_arg:
                    args[current_arg] = " ".join(current_desc).strip()
                parts = line.split(":", 1)
                current_arg = parts[0].strip()
                current_desc = [parts[1].strip()] if len(parts) > 1 else []
            elif current_arg:
                current_desc.append(line.strip())

        if current_arg:
            args[current_arg] = " ".join(current_desc).strip()

        return args

    @staticmethod
    def _parse_raises(lines: List[str]) -> Dict[str, str]:
        """Parse exception descriptions."""
        raises = {}
        current_exc = None
        current_desc = []

        for line in lines:
            # Check if it's an exception definition
            if ":" in line and not line.startswith(" "):
                if current_exc:
                    raises[current_exc] = " ".join(current_desc).strip()
                parts = line.split(":", 1)
                current_exc = parts[0].strip()
                current_desc = [parts[1].strip()] if len(parts) > 1 else []
            elif current_exc:
                current_desc.append(line.strip())

        if current_exc:
            raises[current_exc] = " ".join(current_desc).strip()

        return raises


class DocStringValidator:
    """Validate docstring completeness and correctness."""

    @staticmethod
    def validate_module(module_path: Path) -> List[str]:
        """Validate module documentation.

        Args:
            module_path: Path to module

        Returns:
            List of validation issues
        """
        issues = []

        with open(module_path, "r") as f:
            content = f.read()

        # Parse AST
        tree = ast.parse(content)

        # Check module docstring
        module_doc = ast.get_docstring(tree)
        if not module_doc:
            issues.append("Missing module docstring")
        elif len(module_doc) < 50:
            issues.append("Module docstring too short")

        # Check classes and functions
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node)
                if not doc:
                    issues.append(f"Class {node.name} missing docstring")
                else:
                    class_issues = DocStringValidator._validate_class_doc(
                        node.name, doc
                    )
                    issues.extend(class_issues)

            elif isinstance(node, ast.FunctionDef):
                if not node.name.startswith("_"):  # Skip private methods
                    doc = ast.get_docstring(node)
                    if not doc:
                        issues.append(f"Function {node.name} missing docstring")
                    else:
                        func_issues = DocStringValidator._validate_function_doc(
                            node, doc
                        )
                        issues.extend(func_issues)

        return issues

    @staticmethod
    def _validate_class_doc(class_name: str, docstring: str) -> List[str]:
        """Validate class docstring."""
        issues = []
        parsed = DocStringParser.parse_google_style(docstring)

        if not parsed.get("description"):
            issues.append(f"Class {class_name}: Missing description")

        return issues

    @staticmethod
    def _validate_function_doc(node: ast.FunctionDef, docstring: str) -> List[str]:
        """Validate function docstring."""
        issues = []
        parsed = DocStringParser.parse_google_style(docstring)

        # Check if all parameters are documented
        args = [arg.arg for arg in node.args.args if arg.arg != "self"]
        documented_args = parsed.get("args", {}).keys()

        for arg in args:
            if arg not in documented_args:
                issues.append(f"Function {node.name}: Parameter '{arg}' not documented")

        # Check if return is documented (if function returns something)
        has_return = any(
            isinstance(stmt, ast.Return) and stmt.value is not None
            for stmt in ast.walk(node)
        )
        if has_return and not parsed.get("returns"):
            issues.append(f"Function {node.name}: Missing return documentation")

        return issues


# ============================================================================
# Documentation Generation
# ============================================================================


class DocumentationGenerator:
    """Generate documentation from code."""

    @staticmethod
    def generate_module_doc(module: Any) -> str:
        """Generate module documentation.

        Args:
            module: Module to document

        Returns:
            Generated documentation
        """
        lines = [
            f"# Module: {module.__name__}",
            "",
        ]

        # Module docstring
        if module.__doc__:
            lines.extend(
                [
                    "## Description",
                    "",
                    module.__doc__.strip(),
                    "",
                ]
            )

        # Classes
        classes = []
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and obj.__module__ == module.__name__:
                classes.append((name, obj))

        if classes:
            lines.extend(
                [
                    "## Classes",
                    "",
                ]
            )
            for name, cls in classes:
                lines.append(f"### {name}")
                if cls.__doc__:
                    lines.append(cls.__doc__.strip())
                lines.append("")

                # Methods
                methods = []
                for method_name, method in inspect.getmembers(cls):
                    if inspect.ismethod(method) or inspect.isfunction(method):
                        if not method_name.startswith("_"):
                            methods.append((method_name, method))

                if methods:
                    lines.append("**Methods:**")
                    lines.append("")
                    for method_name, method in methods:
                        sig = inspect.signature(method)
                        lines.append(f"- `{method_name}{sig}`")
                        if method.__doc__:
                            first_line = method.__doc__.strip().split("\n")[0]
                            lines.append(f"  {first_line}")
                    lines.append("")

        # Functions
        functions = []
        for name, obj in inspect.getmembers(module):
            if inspect.isfunction(obj) and obj.__module__ == module.__name__:
                functions.append((name, obj))

        if functions:
            lines.extend(
                [
                    "## Functions",
                    "",
                ]
            )
            for name, func in functions:
                sig = inspect.signature(func)
                lines.append(f"### {name}{sig}")
                if func.__doc__:
                    lines.append(func.__doc__.strip())
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def generate_api_reference(package_path: Path) -> str:
        """Generate API reference for package.

        Args:
            package_path: Path to package

        Returns:
            Generated API reference
        """
        lines = [
            "# API Reference",
            "",
            "## Table of Contents",
            "",
        ]

        # Find all Python files
        py_files = sorted(package_path.glob("**/*.py"))

        toc = []
        content = []

        for py_file in py_files:
            if py_file.name == "__init__.py":
                continue

            module_name = py_file.stem
            relative_path = py_file.relative_to(package_path)

            # Add to TOC
            toc.append(f"- [{module_name}](#{module_name.lower().replace('_', '-')})")

            # Add module documentation
            content.append(f"## {module_name}")
            content.append("")
            content.append(f"**File:** `{relative_path}`")
            content.append("")

            # Try to extract docstring
            try:
                with open(py_file, "r") as f:
                    tree = ast.parse(f.read())
                    doc = ast.get_docstring(tree)
                    if doc:
                        content.append(doc.strip())
                        content.append("")
            except Exception as e:
                content.append(f"*Error parsing module: {e}*")
                content.append("")

        lines.extend(toc)
        lines.append("")
        lines.extend(content)

        return "\n".join(lines)
