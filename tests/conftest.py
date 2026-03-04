import logging
import os
import shutil
from pathlib import Path

import pytest
import salt.utils.platform
from saltfactories.utils import random_string

#  pylint: disable-next=import-error,no-name-in-module
from saltext.dockermod import PACKAGE_ROOT

try:
    import pwd
except ImportError:  # pragma: no cover
    import salt.utils.win_functions

# Reset the root logger to its default level(because salt changed it)
logging.root.setLevel(logging.WARNING)


# This swallows all logging to stdout.
# To show select logs, set --log-cli-level=<level>
for handler in logging.root.handlers[:]:  # pragma: no cover
    logging.root.removeHandler(handler)
    handler.close()


# ----- CLI Options Setup ------------------------------------------------------------------------------------------->
def pytest_addoption(parser):
    """
    register argparse-style options and ini-style config values.
    """
    test_selection_group = parser.getgroup("Tests Selection")
    test_selection_group.addoption(
        "--no-fast",
        "--no-fast-tests",
        dest="fast",
        action="store_true",
        default=False,
        help="Don't run salt-fast tests. Default: %(default)s",
    )
    test_selection_group.addoption(
        "--run-slow",
        "--slow",
        "--slow-tests",
        dest="slow",
        action="store_true",
        default=False,
        help="Run slow tests. Default: %(default)s",
    )


# ----- Register Markers -------------------------------------------------------------------------------------------->
@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    """
    called after command line options have been parsed
    and all plugins and initial conftest files been loaded.
    """
    config.addinivalue_line(
        "markers",
        "slow_test: Mark test as being slow. These tests are skipped by default unless"
        " `--run-slow` is passed",
    )
    # "Flag" the slowTest decorator if we're skipping slow tests or not
    os.environ["SLOW_TESTS"] = str(config.getoption("--run-slow"))


# ----- Test Setup -------------------------------------------------------------------------------------------------->
@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """
    Fixtures injection based on markers or test skips based on CLI arguments
    """
    if item.get_closest_marker("slow_test"):
        if not item.config.getoption("--slow-tests"):
            raise pytest.skip.Exception(
                "Slow tests are disabled, pass '--run-slow' to enable them.",
                _use_item_location=True,
            )
    elif item.config.getoption("--no-fast-tests"):
        raise pytest.skip.Exception(
            "Fast tests have been disabled by '--no-fast-tests'.",
            _use_item_location=True,
        )


@pytest.fixture(scope="session")
def salt_factories_config():  # pragma: no cover
    """
    Return a dictionary with the keyword arguments for FactoriesManager
    """
    return {
        "code_dir": str(PACKAGE_ROOT),
        "inject_sitecustomize": "COVERAGE_PROCESS_START" in os.environ,
        "start_timeout": 120 if os.environ.get("CI") else 60,
    }


@pytest.fixture(scope="package")
def master_config():  # pragma: no cover
    """
    Salt master configuration overrides for integration tests.
    """
    return {}


@pytest.fixture(scope="package")
def master(salt_factories, master_config):  # pragma: no cover
    return salt_factories.salt_master_daemon(random_string("master-"), overrides=master_config)


@pytest.fixture(scope="package")
def minion_config():  # pragma: no cover
    """
    Salt minion configuration overrides for integration tests.
    """
    return {}


@pytest.fixture(scope="package")
def minion(master, minion_config):  # pragma: no cover
    return master.salt_minion_daemon(random_string("minion-"), overrides=minion_config)


@pytest.fixture(scope="session")
def current_user():  # pragma: no cover
    """
    Get the user associated with the current process.
    """
    if salt.utils.platform.is_windows():
        return salt.utils.win_functions.get_current_user(with_domain=False)
    return pwd.getpwuid(os.getuid())[0]


@pytest.fixture(scope="module")
def sshd_server(salt_factories, sshd_config_dir):  # pragma: no cover
    sshd_config_dict = {
        "Protocol": "2",
        # Turn strict modes off so that we can operate in /tmp
        "StrictModes": "no",
        # Logging
        "SyslogFacility": "AUTH",
        "LogLevel": "INFO",
        # Authentication:
        "LoginGraceTime": "120",
        "PermitRootLogin": "without-password",
        "PubkeyAuthentication": "yes",
        # Don't read the user's ~/.rhosts and ~/.shosts files
        "IgnoreRhosts": "yes",
        "HostbasedAuthentication": "no",
        # To enable empty passwords, change to yes (NOT RECOMMENDED)
        "PermitEmptyPasswords": "no",
        # Change to yes to enable challenge-response passwords (beware issues with
        # some PAM modules and threads)
        "ChallengeResponseAuthentication": "no",
        # Change to no to disable tunnelled clear text passwords
        "PasswordAuthentication": "no",
        "X11Forwarding": "no",
        "X11DisplayOffset": "10",
        "PrintMotd": "no",
        "PrintLastLog": "yes",
        "TCPKeepAlive": "yes",
        "AcceptEnv": "LANG LC_*",
        "UsePAM": "yes",
    }
    sftp_server_paths = [
        # Common
        "/usr/lib/openssh/sftp-server",
        # CentOS Stream 9
        "/usr/libexec/openssh/sftp-server",
        # Arch Linux
        "/usr/lib/ssh/sftp-server",
        # Photon OS 5
        "/usr/libexec/sftp-server",
    ]
    sftp_server_path = None
    for path in sftp_server_paths:
        if Path(path).exists():
            sftp_server_path = path
    if sftp_server_path is None:
        pytest.fail(f"Failed to find 'sftp-server'. Searched: {sftp_server_paths}")
    else:
        sshd_config_dict["Subsystem"] = f"sftp {sftp_server_path}"
    factory = salt_factories.get_sshd_daemon(
        sshd_config_dict=sshd_config_dict,
        config_dir=sshd_config_dir,
    )
    with factory.started():
        yield factory


@pytest.fixture(scope="module")
def known_hosts_file(sshd_server, master, salt_factories):  # pragma: no cover
    with (
        pytest.helpers.temp_file(
            "ssh-known-hosts",
            "\n".join(sshd_server.get_host_keys()),
            salt_factories.tmp_root_dir,
        ) as known_hosts_file,
        pytest.helpers.temp_file(
            "master.d/ssh-known-hosts.conf",
            f"known_hosts_file: {known_hosts_file}",
            master.config_dir,
        ),
    ):
        yield known_hosts_file


@pytest.fixture(scope="module")
def salt_ssh_roster_file(
    sshd_server, master, known_hosts_file, current_user
):  # pylint: disable=unused-argument; pragma: no cover
    roster_contents = f"""
    localhost:
      host: 127.0.0.1
      port: {sshd_server.listen_port}
      user: {current_user}
    """
    if salt.utils.platform.is_darwin():
        roster_contents += "  set_path: $PATH:/usr/local/bin/\n"

    with pytest.helpers.temp_file("roster", roster_contents, master.config_dir) as roster_file:
        yield roster_file


@pytest.fixture(scope="session")
def sshd_config_dir(salt_factories):  # pragma: no cover
    config_dir = salt_factories.get_root_dir_for_daemon("sshd")
    try:
        yield config_dir
    finally:
        shutil.rmtree(str(config_dir), ignore_errors=True)
