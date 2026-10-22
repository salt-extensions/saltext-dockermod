Fix ``docker_network.present`` recreating an IPv6-enabled network without explicit IPAM pools on every run, by treating any number of Docker-assigned default IPAM pools as auto-assigned.
