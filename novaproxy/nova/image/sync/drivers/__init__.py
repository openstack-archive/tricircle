import nova.image.sync.drivers.filesystem


_store_drivers_map = {
    'file:file':filesystem.Store

}


def get_store_driver(scheme_key):
    cls = _store_drivers_map.get(scheme_key)
    return cls()