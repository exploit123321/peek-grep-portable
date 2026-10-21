"""Test setup: keep settings and the index in a temporary data folder, never in the real one."""

import os
import tempfile

_TEST_DATA = tempfile.mkdtemp(prefix="peekgrep-test-data-")
os.environ["PEEK_GREP_DATA"] = _TEST_DATA
os.environ.pop("PEEK_GREP_DB_PATH", None)
os.environ.pop("PEEK_GREP_SETTINGS", None)
