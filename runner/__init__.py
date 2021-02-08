"""
Test Runner for Python.
"""
import os
import re
from textwrap import dedent
from typing import List
from pathlib import Path
import json

import pytest

from .data import Slug, Directory, Hierarchy, Results, Test
from .sort import TestOrder


class ResultsReporter:
    def __init__(self):
        self.results = Results()
        self.tests = {}
        self.last_err = None
        self.config = None

    def pytest_configure(self, config):
        self.config = config

    def pytest_collection_modifyitems(self, session, config, items):
        """
        Sorts the tests in definition order.
        """

        def _sort_by_lineno(item):
            test_id = Hierarchy(item.nodeid)
            source = Path(item.fspath)
            return TestOrder.lineno(test_id, source)

        items.sort(key=_sort_by_lineno)

    def pytest_runtest_logreport(self, report):
        """
        Process a test setup / call / teardown report.
        """
        name = ".".join(report.nodeid.split("::")[1:])
        if name not in self.tests:
            self.tests[name] = Test(name)
        state = self.tests[name]

        # ignore succesful setup and teardown stages
        if report.passed and report.when != "call":
            return

        # do not update tests that have already failed
        if not state.is_passing():
            return

        # captured stdout content, if any
        if report.capstdout:
            state.output = report.capstdout

        # handle test failure
        if report.failed:

            # traceback that caused the issued, if any
            message = None
            if report.longrepr:
                trace = report.longrepr.reprtraceback
                crash = report.longrepr.reprcrash
                message = self._make_message(trace, crash)

            # test failed due to a setup / teardown error
            if report.when != "call":
                state.error(message)
            else:
                state.fail(message)

        test_id = Hierarchy(report.nodeid)
        source = Path(self.config.rootdir) / report.fspath
        state.test_code = TestOrder.function_source(test_id, source)

    def pytest_sessionfinish(self, session, exitstatus):
        """
        Processes the results into a report.
        """
        exitcode = pytest.ExitCode(int(exitstatus))

        # at least one of the tests has failed
        if exitcode is pytest.ExitCode.TESTS_FAILED:
            self.results.fail()

        # an error has been encountered
        elif exitcode is not pytest.ExitCode.OK:
            message = None
            if self.last_err is not None:
                message = self.last_err
            else:
                message = f"Unexpected ExitCode.{exitcode.name}: check logs for details"
            self.results.error(message)

        for test in self.tests.values():
            self.results.add(test)

    def pytest_terminal_summary(self, terminalreporter):
        """
        Report to the terminal that the reporter has run.
        """
        terminalreporter.write_sep("-", "generated results.json")

    def pytest_exception_interact(self, node, call, report):
        """
        Catch the last exception handled in case the test run itself errors.
        """
        if report.outcome == "failed":
            excinfo = call.excinfo
            err = excinfo.getrepr(style="no", abspath=False)
            trace = err.chain[0][0]
            crash = err.chain[0][1]
            self.last_err = self._make_message(trace, crash)

    def _make_message(self, trace, crash=None):
        """
        Make a formatted message for reporting.
        """
        # stringify the traceback, strip pytest-specific formatting
        message = dedent(re.sub("^E ", "  ", str(trace), flags=re.M))

        # if a path exists that's relative to the runner we can strip it out
        if crash:
            common = os.path.commonpath([Path.cwd(), Path(crash.path)])
            message = message.replace(common, ".")
        return message


def _sanitize_args(args: List[str]) -> List[str]:
    clean = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--tb":
            skip_next = True
            continue
        elif arg.startswith("--tb="):
            continue
        clean.append(arg)
    clean.append("--tb=no")
    return clean


def run(slug: Slug, indir: Directory, outdir: Directory, args: List[str]) -> None:
    """
    Run the tests for the given exercise and produce a results.json.
    """
    test_files = []
    config_file = indir.joinpath(".meta").joinpath("config.json")
    if config_file.is_file():
        config_data = json.loads(config_file.read_text())
        for filename in config_data.get('files', {}).get('test', []):
            test_files.append(indir.joinpath(filename))
    if not test_files:
        test_files.append(indir.joinpath(slug.replace("-", "_") + "_test.py"))
    out_file = outdir.joinpath("results.json")
    # run the tests and report
    reporter = ResultsReporter()
    pytest.main(_sanitize_args(args or []) + [str(tf) for tf in test_files], plugins=[reporter])
    # dump the report
    out_file.write_text(reporter.results.as_json())
    out_file.chmod(664)
