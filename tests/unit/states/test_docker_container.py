"""
Unit tests for the docker_container state
"""

from unittest.mock import patch

import pytest

import saltext.dockermod.modules.dockermod as docker_mod
import saltext.dockermod.states.docker_container as docker_state

NAME = "foo"
TEMP_NAME = "temp-container"
NETWORK = "net1"
IMAGE_ID = "sha256:" + "0" * 64
EXISTING_ID = "a" * 64
TEMP_ID = "b" * 64


@pytest.fixture
def configure_loader_modules():
    return {
        docker_mod: {"__context__": {"docker.docker_version": ""}},
        docker_state: {"__opts__": {"test": False}, "__context__": {}},
    }


class FakeDocker:
    """
    Minimal in-memory stand-in for the docker execution module, tracking the containers which
    docker_container.running creates, inspects, removes, renames, starts and (dis)connects to
    networks.
    """

    def __init__(self, existing_command, existing_networks, existing_state):
        self.state = existing_state
        self.containers = {
            NAME: self._container(EXISTING_ID, NAME, existing_command, existing_networks)
        }

    @staticmethod
    def _container(container_id, name, command, networks):
        return {
            "Id": container_id,
            "Name": name,
            "Image": IMAGE_ID,
            "Config": {"Cmd": command},
            "HostConfig": {},
            "NetworkSettings": {"Networks": {net: {} for net in networks}},
        }

    def inspect_container(self, name):
        return self.containers[name]

    def create(self, image, name=None, command=None, **kwargs):
        name = name or TEMP_NAME
        self.containers[name] = self._container(TEMP_ID, name, command, ())
        return {"Id": TEMP_ID, "Name": name}

    def rm(self, name, **kwargs):
        return [self.containers.pop(name)["Id"]]

    def rename(self, name, new_name):
        self.containers[new_name] = self.containers.pop(name)
        self.containers[new_name]["Name"] = new_name
        return True

    def start(self, name):
        old_state, self.state = self.state, "running"
        return {"state": {"old": old_state, "new": self.state}}

    def connected(self, net_name):
        return [
            name
            for name, container in self.containers.items()
            if net_name in container["NetworkSettings"]["Networks"]
        ]

    def connect_container_to_network(self, container, net_name, **kwargs):
        self.containers[container]["NetworkSettings"]["Networks"][net_name] = {}

    def disconnect_container_from_network(self, container, net_name):
        del self.containers[container]["NetworkSettings"]["Networks"][net_name]

    @staticmethod
    def compare_container_networks(first, second):
        nets1 = first["NetworkSettings"]["Networks"]
        nets2 = second["NetworkSettings"]["Networks"]
        return {
            net_name: {"Connected": {"old": net_name in nets1, "new": net_name in nets2}}
            for net_name in set(nets1) ^ set(nets2)
        }

    def salt_functions(self):
        return {
            "config.option": lambda key: {},
            "docker.compare_container_networks": self.compare_container_networks,
            # The real comparison is used, reading containers through the patched
            # docker_mod.inspect_container.
            "docker.compare_containers": docker_mod.compare_containers,
            "docker.connect_container_to_network": self.connect_container_to_network,
            "docker.connected": self.connected,
            "docker.create": self.create,
            "docker.disconnect_container_from_network": self.disconnect_container_from_network,
            "docker.inspect_container": self.inspect_container,
            "docker.networks": lambda: [{"Name": NETWORK}],
            "docker.rename": self.rename,
            "docker.resolve_image_id": lambda image: IMAGE_ID,
            "docker.rm": self.rm,
            "docker.start": self.start,
            "docker.state": lambda name: self.state,
            "docker.version": lambda: {"VersionInfo": (29, 1, 0)},
        }


@pytest.mark.parametrize(
    "existing_command,existing_networks,existing_state,change_keys,force_mod_watch",
    [
        pytest.param("sleep 600", [NETWORK], "running", set(), False, id="unchanged"),
        pytest.param("sleep 600", [], "running", {"container"}, True, id="networks"),
        pytest.param(
            "sleep 1200",
            [NETWORK],
            "running",
            {"container", "container_id"},
            False,
            id="replaced",
        ),
        pytest.param(
            "sleep 1200",
            [],
            "running",
            {"container", "container_id"},
            False,
            id="replaced-and-networks",
        ),
        pytest.param("sleep 600", [NETWORK], "stopped", {"state"}, False, id="started"),
        pytest.param(
            "sleep 600",
            [],
            "stopped",
            {"container", "state"},
            False,
            id="started-and-networks",
        ),
    ],
)
def test_running_force_mod_watch(
    existing_command, existing_networks, existing_state, change_keys, force_mod_watch
):
    """
    force_mod_watch must be returned only when the normal run made changes but did not replace or
    restart the container, so that a watch requisite still triggers mod_watch.
    """
    docker = FakeDocker(existing_command, existing_networks, existing_state)
    with (
        patch.dict(docker_state.__dict__, {"__salt__": docker.salt_functions()}),
        patch.object(docker_mod, "inspect_container", docker.inspect_container),
    ):
        ret = docker_state.running(
            NAME, image="bar:latest", command="sleep 600", networks=[NETWORK]
        )

    assert ret["result"] is True
    assert set(ret["changes"]) == change_keys
    assert ret.get("force_mod_watch", False) is force_mod_watch
    assert list(docker.containers[NAME]["NetworkSettings"]["Networks"]) == [NETWORK]
    assert docker.state == "running"
