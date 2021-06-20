import re
from collections import Counter

import docker
from mpublisher import AvahiPublisher

LOCAL_CNAME = "local_cname"
docker = docker.from_env()
START_EVENT = "start"
DIE_EVENT = "die"
TRAEFIK_ON = "traefik.enable"
TRAEFIK_WHOAMI = "traefik.http.routers.whoami.rule"

traefik_rule_re = re.compile(r"Host\b\(`([^`]+.local)`\)")


class RefCountedPublisher(AvahiPublisher):
    # This is useful in case of having several
    # instances of the same docker-compose service
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._counts = Counter()

    def publish_cname(self, name, force=False):
        if not self._counts[name] or force:
            super().publish_cname(name, force=force)
            print(f"Adding {name}")
        self._counts[name] += 1
        print(f"RC {name} { self._counts[name] }")

    def unpublish_cname(self, name, force=False):
        if self._counts[name] == 1:
            super().unpublish_cname(name, force=force)
            print(f"Removing {name}")
        self._counts[name] -= 1
        print(f"RC {name} { self._counts[name] }")


publisher = RefCountedPublisher()


def container_to_cnames(container):
    return _attributes_to_cnames(container.labels)


def _event_to_labels(e):
    return e.get("Actor", {}).get("Attributes", {})


def _attributes_to_cnames(attribs):
    cnames = []

    if name := attribs.get(LOCAL_CNAME):
        if name in (True, "True"):
            cnames.append(attribs.get("com.docker.compose.service"))
        else:
            cnames.append(name)
    cnames = [f"{cname}.local" for cname in cnames]
    if attribs.get(TRAEFIK_ON):
        rules = attribs.get(TRAEFIK_WHOAMI, "")
        for (cname,) in traefik_rule_re.findall(rules):
            cnames.append(cname)

    return cnames


def event_to_actions(event):
    status = event.get("status")
    if status not in [START_EVENT, DIE_EVENT]:
        return []

    labels = _event_to_labels(event)
    cnames = _attributes_to_cnames(labels)
    return [(status, cname) for cname in cnames]


def main():
    for container in docker.containers.list():
        for cname in container_to_cnames(container):
            publisher.publish_cname(cname)

    for event in docker.events(decode=True):
        for status, cname in event_to_actions(event):
            if status == START_EVENT:
                publisher.publish_cname(cname)
            elif status == DIE_EVENT:
                publisher.unpublish_cname(cname)


if __name__ == "__main__":
    main()
