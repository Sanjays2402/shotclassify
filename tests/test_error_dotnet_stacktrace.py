""".NET / CLR stacktrace parser tests.

Adds .NET to the existing extractor catalog (Python / Node / JVM / Go /
Ruby / HTTP). The framework field uses the lowercase tag ``dotnet``
consistent with the rest of the catalog. The exception name keeps its
full namespace (``System.NullReferenceException``) so dashboards can
group by either short or full form.

Detection rules:
* A frame with ``in FILE.cs:line N`` (the form ``dotnet build`` prints
  when symbols are available) is sufficient on its own.
* A bare frame ``at NS.T.M(args)`` is only enough when an exception
  line like ``System.NullReferenceException: msg`` is also present.

The .NET branch is intentionally placed BEFORE the JVM branch so a
CLR trace whose exception line (``System.NullReferenceException``)
would also match the JVM regex still tags as .NET. JVM detection is
safe because Java convention starts package segments lowercase
(``java.lang.NullPointerException``) and the .NET exception regex
requires every segment to start uppercase.
"""
from __future__ import annotations

from shotclassify_extract.error import parse_error_text


def test_dotnet_nullreference_with_file_and_line():
    text = (
        "System.NullReferenceException: Object reference not set to an instance of an object.\n"
        "   at MyApp.Service.GetUser(Int32 id) in C:\\src\\MyApp\\Service.cs:line 42\n"
        "   at MyApp.Program.Main(String[] args) in C:\\src\\MyApp\\Program.cs:line 10\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "dotnet"
    assert fields.exception == "System.NullReferenceException"
    assert "Object reference" in (fields.message or "")
    # innermost (last) frame wins, mirroring Python/Go behaviour.
    assert fields.file == "C:\\src\\MyApp\\Program.cs"
    assert fields.line == 10
    assert fields.likely_cause is not None
    assert "null" in fields.likely_cause.lower()


def test_dotnet_invalidoperation_with_file_and_line():
    text = (
        "System.InvalidOperationException: Sequence contains no elements\n"
        "   at System.Linq.Enumerable.First[TSource](IEnumerable`1 source)\n"
        "   at MyApp.Repo.LoadFirst() in /app/src/Repo.cs:line 88\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "dotnet"
    assert fields.exception == "System.InvalidOperationException"
    assert fields.file == "/app/src/Repo.cs"
    assert fields.line == 88
    assert "state" in (fields.likely_cause or "").lower()


def test_dotnet_bare_frames_require_exception_line():
    """A bare ``at NS.T.M(args)`` frame alone is NOT enough -- it must
    pair with a ``System.X.YException:`` exception line, otherwise we
    let the generic regex / JVM branch handle it."""
    text = (
        "System.ArgumentNullException: Value cannot be null. (Parameter 'name')\n"
        "   at MyApp.User.Greet(String name)\n"
        "   at MyApp.Program.Main()\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "dotnet"
    assert fields.exception == "System.ArgumentNullException"
    # No "in foo.cs:line N" -> no file/line.
    assert fields.file is None
    assert fields.line is None
    assert "null" in (fields.likely_cause or "").lower()


def test_dotnet_filenotfound_likely_cause():
    text = (
        "System.IO.FileNotFoundException: Could not load file or assembly 'Plugin'.\n"
        "   at System.Reflection.Assembly.Load(String name)\n"
        "   at MyApp.Loader.LoadPlugin() in /opt/app/Loader.cs:line 17\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "dotnet"
    assert fields.exception == "System.IO.FileNotFoundException"
    assert "missing on disk" in (fields.likely_cause or "")


def test_dotnet_indexoutofrange_likely_cause():
    text = (
        "System.IndexOutOfRangeException: Index was outside the bounds of the array.\n"
        "   at MyApp.Buffer.At(Int32 i) in /srv/Buffer.cs:line 5\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "dotnet"
    assert fields.exception == "System.IndexOutOfRangeException"
    assert "outside the allowed range" in (fields.likely_cause or "")


def test_dotnet_taskcanceled_likely_cause():
    text = (
        "System.Threading.Tasks.TaskCanceledException: A task was canceled.\n"
        "   at MyApp.HttpClient.SendAsync() in /app/Net.cs:line 22\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "dotnet"
    assert "cancelled" in (fields.likely_cause or "")


def test_jvm_still_wins_over_dotnet_when_lowercase_namespace():
    """JVM exception namespaces start lowercase (``java.lang.X``) so
    the .NET regex never matches them and the JVM branch keeps the
    trace. Regression for the catalog ordering."""
    text = (
        "Exception in thread \"main\" java.lang.NullPointerException: oops\n"
        "    at com.example.App.run(App.java:42)\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "jvm"
    assert fields.exception == "java.lang.NullPointerException"


def test_python_still_wins_when_traceback_present_with_dotnet_string():
    """Regression: a Python traceback that mentions a .NET-looking name
    inside a string literal must still classify as python."""
    text = (
        'Traceback (most recent call last):\n'
        '  File "/x.py", line 1, in <module>\n'
        '    raise RuntimeError("System.NullReferenceException came back")\n'
        'RuntimeError: System.NullReferenceException came back\n'
    )
    fields = parse_error_text(text)
    assert fields.framework == "python"
    assert fields.exception == "RuntimeError"


def test_dotnet_with_generic_method_type_arguments():
    """Real CLR frames sometimes include backtick-suffixed generics:
    ``at System.Collections.Generic.List`1.Add(T item)``. Make sure
    the bare-frame regex still recognises them."""
    text = (
        "System.ArgumentException: Item already exists\n"
        "   at System.Collections.Generic.List`1.Add(Object item)\n"
        "   at MyApp.Cache.Store(Object x)\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "dotnet"
    assert fields.exception == "System.ArgumentException"
