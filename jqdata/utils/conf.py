import yaml


def read(filename):
    with open(filename) as f:
        return yaml.load(f.read())


def update(origin, conf):
    assert isinstance(origin, dict)
    assert isinstance(conf, dict)
    for key, value in conf.items():
        if isinstance(value, dict):
            update(origin.setdefault(key, {}), value)
        elif isinstance(value, list):
            origin.setdefault(key, []).extend(value)
        else:
            origin[key] = value


def load(filename, config):
    update(config, read(filename))