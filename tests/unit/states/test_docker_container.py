"""
Unit tests for the docker_container state
"""

from unittest.mock import patch

import pytest

import saltext.dockermod.modules.dockermod as docker_mod
import saltext.dockermod.states.docker_container as docker_state

NAME = "foo"
TEMP_NAME = "temp-container"
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
    docker_container.running creates, inspects, removes and renames.
    """

    def __init__(self, existing_hostname, docker_version):
        self.docker_version = docker_version
        self.containers = {NAME: self._container(EXISTING_ID, NAME, existing_hostname)}

    @staticmethod
    def _container(container_id, name, hostname):
        return {
            "Id": container_id,
            "Name": name,
            "Image": IMAGE_ID,
            # Docker assigns the short container ID as the hostname when none is set explicitly.
            "Config": {"Hostname": hostname or container_id[:12]},
            "HostConfig": {},
            "NetworkSettings": {"Networks": {}},
        }

    def inspect_container(self, name):
        return self.containers[name]

    def create(self, image, name=None, **kwargs):
        name = name or TEMP_NAME
        self.containers[name] = self._container(TEMP_ID, name, kwargs.get("hostname"))
        return {"Id": TEMP_ID, "Name": name}

    def rm(self, name, **kwargs):
        return [self.containers.pop(name)["Id"]]

    def rename(self, name, new_name):
        self.containers[new_name] = self.containers.pop(name)
        self.containers[new_name]["Name"] = new_name
        return True

    def salt_functions(self):
        return {
            "config.option": lambda key: {},
            "docker.compare_container_networks": lambda first, second: {},
            # The real comparison is used, reading containers through the patched
            # docker_mod.inspect_container.
            "docker.compare_containers": docker_mod.compare_containers,
            "docker.create": self.create,
            "docker.inspect_container": self.inspect_container,
            "docker.rename": self.rename,
            "docker.resolve_image_id": lambda image: IMAGE_ID,
            "docker.rm": self.rm,
            "docker.start": lambda name: {"state": {"old": "stopped", "new": "running"}},
            "docker.state": lambda name: "running",
            "docker.version": lambda: {"VersionInfo": self.docker_version},
        }


@pytest.mark.parametrize("docker_version", [(24, 0, 7), (29, 1, 0)])
@pytest.mark.parametrize(
    "existing_hostname,hostname,replaced",
    [
        (None, None, False),
        ("web1", "web1", False),
        ("web1", "web2", True),
        (None, "web1", True),
    ],
)
def test_running_hostname(docker_version, existing_hostname, hostname, replaced):
    """
    Hostname is compared only when it is set explicitly: the container must be replaced when the
    explicitly set hostname changes, but not because of the hostname Docker auto-assigns.
    """
    docker = FakeDocker(existing_hostname, docker_version)
    kwargs = {"hostname": hostname} if hostname else {}
    with (
        patch.dict(docker_state.__dict__, {"__salt__": docker.salt_functions()}),
        patch.object(docker_mod, "inspect_container", docker.inspect_container),
    ):
        ret = docker_state.running(NAME, image="bar:latest", **kwargs)

    assert ret["result"] is True
    assert TEMP_NAME not in docker.containers
    if replaced:
        assert ret["changes"] == {
            "container": {
                "Config": {
                    "Hostname": {"old": existing_hostname or EXISTING_ID[:12], "new": hostname}
                }
            },
            "container_id": {"removed": [EXISTING_ID], "added": TEMP_ID},
        }
        assert ret["comment"] == f"Replaced container '{NAME}'"
        assert docker.containers[NAME]["Id"] == TEMP_ID
        assert docker.containers[NAME]["Config"]["Hostname"] == hostname
    else:
        assert not ret["changes"]
        assert ret["comment"] == f"Container '{NAME}' is already configured as specified"
        assert docker.containers[NAME]["Id"] == EXISTING_ID
