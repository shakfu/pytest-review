# TODO

Potential improvements to test quality heuristics, organized by analyzer.

## High signal-to-noise (implement first)

### Patterns

- [x] **`subprocess.run` without `check=True`**: `subprocess.run()` without `check=True` silently ignores failures. Detect absence of `check=True` in keyword arguments via AST. (WARNING)

- [x] **Broad `pytest.raises(Exception)`**: Catching base `Exception` in `pytest.raises` is the exception-handling equivalent of a bare `except`. Flag with suggestion to use a specific exception type. (WARNING)

### Isolation

- [x] **`os.environ` mutations**: Direct writes to `os.environ["KEY"]` or `os.environ.update(...)` are shared state modifications. Flag with specific rule (`isolation.env_mutation`) and suggest `monkeypatch.setenv`. (WARNING)

### Smells

- [x] **Conditional logic in tests**: Tests with `if/else` branches often indicate the test should be split or use `@pytest.mark.parametrize`. Dedicated `smells.conditional_test` rule. (WARNING)

- [x] **Fixture overuse / parameter count**: A test function with > 5-6 parameters (fixtures) suggests poor fixture composition. Countable from `ast.FunctionDef.args`. (INFO)

## Medium signal-to-noise

### Assertions

- [x] **Low-value assertions**: `assert isinstance(result, dict)` or `assert x is not None` confirm type/existence without checking actual behavior. Flag as INFO-level "weak assertion" to push toward value-checking assertions.

- [x] **Missing `pytest.raises` message match**: `with pytest.raises(ValueError):` without `match=` keyword doesn't verify the exception message. Flag as INFO when `match` is absent.

### Naming

- [x] **Redundant test prefix duplication**: Names like `test_test_connection` stutter. Regex check for repeated words in test names. (INFO)

- [x] **Missing verb / action word**: Good test names describe behavior (`test_rejects_invalid_email`). Check whether name after `test_` starts with a common verb (`returns`, `raises`, `creates`, `handles`, `rejects`, `validates`, `detects`, etc.). (INFO)

### Patterns

- [x] **Mutable default arguments**: `def helper(items=[])` is a classic Python bug. Detect `ast.FunctionDef` arguments with mutable defaults (`[]`, `{}`, `set()`). (WARNING)

### Isolation

- [x] **`mock.patch` without cleanup**: `mock.patch.object(Foo, 'bar', new_value)` called bare (without `with` or `addCleanup`) can leak state. Detect `patch`/`patch.object` calls outside `with` statements, analogous to the `open()` check. (WARNING)

### Smells

- [x] **Test-internal `try/except`**: A test that catches its own exceptions may be masking failures. Flag any `try` block directly inside a test function body. (WARNING)

### Complexity

- [x] **Assertion-to-logic ratio**: A test with many lines of setup/logic and few assertions is a smell distinct from raw statement count. Flag when assertions are < 10% of statements. (INFO)

- [x] **Excessive `@pytest.mark.parametrize` combinations**: Large parameter sets (> 20 cases) may indicate the test is doing too much. Count tuples in the decorator argument. (INFO)

## Lower signal-to-noise (team-dependent)

### Assertions

- [x] **Yoda conditions**: `assert 42 == x` instead of `assert x == 42`. Minor readability issue, easy to detect by checking if the left operand of `ast.Compare` is a constant. (INFO)

### Performance (static)

- [x] **Static detection of slow operations**: Beyond `time.sleep()`, flag network calls (`requests.get/post`, `httpx.get/post`, `urllib.request.urlopen`), disk I/O in loops (`open()` inside `for`), and database operations without mocking hints (`cursor.execute`, `session.query`). (INFO)

### Cross-cutting

- [ ] **Test file organization**: Per-file rather than per-function: flag test files with > 30 test functions or > 500 lines. Would be a new analyzer or extension to complexity operating at file granularity. (INFO)
