"""
Unit tests for the docker_network state
"""

import copy
from unittest.mock import patch

import pytest
from salt.exceptions import CommandExecutionError

import saltext.dockermod.modules.dockermod as docker_mod
import saltext.dockermod.states.docker_network as docker_state

NAME = "foo"
CONTAINER_ID = "c" * 64
CONTAINER_NAME = "web"
IPV4_SUBNET = "10.247.197.96/27"
IPV4_GATEWAY = "10.247.197.97"
IPV4_ADDRESS = "10.247.197.100"
IPV6_SUBNET = "fe3f:2180:26:1::/123"
IPV6_GATEWAY = "fe3f:2180:26:1::1"
IPV6_ADDRESS = "fe3f:2180:26:1::10"


@pytest.fixture
def configure_loader_modules():
    return {
        docker_mod: {"__context__": {"docker.docker_version": ""}},
        docker_state: {"__opts__": {"test": False}},
    }


class FakeDocker:
    """
    Minimal in-memory stand-in for the docker execution module, tracking the networks which
    docker_network.present creates, inspects and removes, and the containers it connects to them.
    """

    def __init__(self):
        self.networks = {}
        self.connect_calls = []
        self.create_network(
            NAME,
            enable_ipv6=True,
            ipam={
                "Driver": "default",
                "Options": {},
                "Config": [
                    {"Subnet": IPV4_SUBNET, "Gateway": IPV4_GATEWAY},
                    {"Subnet": IPV6_SUBNET, "Gateway": IPV6_GATEWAY},
                ],
            },
        )
        self.networks[NAME]["Containers"][CONTAINER_ID] = {
            "Name": CONTAINER_NAME,
            "IPv4Address": f"{IPV4_ADDRESS}/27",
            "IPv6Address": f"{IPV6_ADDRESS}/123",
        }

    def create_network(self, name, skip_translate=None, enable_ipv6=False, **kwargs):
        self.networks[name] = {
            "Name": name,
            "Id": f"{name}-id",
            "Driver": kwargs.get("driver") or "bridge",
            "EnableIPv6": enable_ipv6,
            "IPAM": kwargs.get("ipam") or {"Driver": "default", "Options": {}, "Config": []},
            "Labels": kwargs.get("labels") or {},
            "Options": kwargs.get("options") or {},
            "Containers": {},
        }

    def inspect_network(self, name):
        try:
            return copy.deepcopy(self.networks[name])
        except KeyError:
            raise CommandExecutionError(f"Error 404: No such network: {name}") from None

    def remove_network(self, name):
        del self.networks[name]

    def inspect_container(self, name):
        return {
            "Name": f"/{CONTAINER_NAME}",
            "NetworkSettings": {"Networks": {NAME: {"Aliases": None, "Links": None}}},
        }

    def connect_container_to_network(self, container, net_id, **kwargs):
        self.connect_calls.append((container, net_id, kwargs))
        self.networks[net_id]["Containers"][container] = {"Name": CONTAINER_NAME}

    def disconnect_container_from_network(self, container, network_id):
        del self.networks[network_id]["Containers"][container]

    def salt_functions(self):
        return {
            "docker.compare_networks": docker_mod.compare_networks,
            "docker.connect_container_to_network": self.connect_container_to_network,
            "docker.create_network": self.create_network,
            "docker.disconnect_container_from_network": self.disconnect_container_from_network,
            "docker.get_client_args": docker_mod.get_client_args,
            "docker.inspect_container": self.inspect_container,
            "docker.inspect_network": self.inspect_network,
            "docker.remove_network": self.remove_network,
        }


def test_present_reconnect_static_ips():
    """
    When a network is recreated, the containers which were connected to it must be reconnected
    with their previous IPv4 and IPv6 addresses.
    """
    docker = FakeDocker()
    with patch.dict(docker_state.__dict__, {"__salt__": docker.salt_functions()}):
        # A new label forces the network to be recreated.
        ret = docker_state.present(
            NAME,
            enable_ipv6=True,
            ipam_pools=[
                {"subnet": IPV4_SUBNET, "gateway": IPV4_GATEWAY},
                {"subnet": IPV6_SUBNET, "gateway": IPV6_GATEWAY},
            ],
            labels=["bar"],
        )

    assert ret["result"] is True
    assert ret["changes"] == {
        NAME: {"Labels": {"old": {}, "new": {"bar": ""}}},
        "recreated": True,
        "reconnected": [CONTAINER_NAME],
    }
    assert docker.connect_calls == [
        (CONTAINER_ID, NAME, {"ipv4_address": IPV4_ADDRESS, "ipv6_address": IPV6_ADDRESS})
    ]
    assert list(docker.networks) == [NAME]
