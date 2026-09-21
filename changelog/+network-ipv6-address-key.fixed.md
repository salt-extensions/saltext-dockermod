Fix ``docker_network.present`` not restoring a container's IPv6 address when reconnecting it to a recreated network, due to a typo in the ``IPv6Address`` key.
