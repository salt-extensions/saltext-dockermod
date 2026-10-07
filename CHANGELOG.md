The changelog format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

This project uses [Semantic Versioning](https://semver.org/) - MAJOR.MINOR.PATCH

# Changelog

## 0.1.4 (2026-10-07)


### Fixed

- Do not delete already existing composefile when editing it fails. [#18](https://github.com/salt-extensions/saltext-dockermod/issues/18)
- Fixed ``docker_network.present`` reporting spurious changes and recreating a network on every run when a ``subnet`` was specified without a ``gateway``. Docker auto-assigns the subnet's first host address as the gateway and reports it on inspect, while Salt's desired config omits the key entirely; ``docker.compare_networks`` now ignores a one-sided gateway only when it matches that auto-assigned default, so an explicitly added, removed, or changed gateway is still detected as a real change. [#22](https://github.com/salt-extensions/saltext-dockermod/issues/22)

## 0.1.3 (2026-09-21)

No significant changes.


## 0.1.2 (2026-09-18)


### Fixed

- Add docker source files that were missed when creating the dockermod extension. [#6](https://github.com/salt-extensions/saltext-dockermod/issues/6)

## v0.1.1 (2026-03-05)

No significant changes.


## v0.1.0 (2026-03-04)


### Fixed

- Backport https://github.com/saltstack/salt/pull/68270 to fix the failing tests. [#3](https://github.com/salt-extensions/saltext-dockermod/pull/3)
