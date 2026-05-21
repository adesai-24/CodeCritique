# Test fixture: intentional security issues that Bandit should flag.
# Used to validate that BanditChecker catches high/medium severity problems.

import subprocess  # noqa: S404


SECRET_KEY = "hardcoded-super-secret-key-do-not-use"  # noqa: S105


def run_query(user_input: str):
    # SQL injection via string formatting — no parameterisation.
    query = "SELECT * FROM users WHERE name = '%s'" % user_input  # noqa: S608
    return query


def execute_command(cmd: str):
    # Shell injection — passing user input directly to shell=True.
    subprocess.run(cmd, shell=True)  # noqa: S602
