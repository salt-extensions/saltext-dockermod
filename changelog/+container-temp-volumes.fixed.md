Fixed ``docker_container.running`` leaking the anonymous volumes of the temporary container it creates to compare against an existing container, one per run for images that declare a ``VOLUME``.
