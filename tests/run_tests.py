"""Run every test. From the project folder: python -m tests.run_tests"""

from tests import test_config, test_database_and_workflow, test_policies
from tests import test_simulation, test_validation
from tests.support import run_tests

ALL_TESTS = (test_config.TESTS + test_policies.TESTS + test_simulation.TESTS
             + test_validation.TESTS + test_database_and_workflow.TESTS)

if __name__ == "__main__":
    failures = run_tests(ALL_TESTS)
    # A non-zero exit code tells the terminal (or a CI job) that something failed.
    raise SystemExit(1 if failures else 0)
