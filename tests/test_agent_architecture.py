from core.agent_architecture import (
    LAYERS, PLATFORM_COMPONENTS, SPECIALIST_MODULES, validate_inventory,
)


def test_inventory_has_23_specialist_modules_and_9_platform_components():
    assert len(SPECIALIST_MODULES) == 23
    assert len(PLATFORM_COMPONENTS) == 9


def test_inventory_keys_and_modules_are_unique():
    assert len({item.key for item in SPECIALIST_MODULES}) == len(SPECIALIST_MODULES)
    assert len({item.module for item in SPECIALIST_MODULES}) == len(SPECIALIST_MODULES)
    assert len({item.key for item in PLATFORM_COMPONENTS}) == len(PLATFORM_COMPONENTS)
    assert len({item.module for item in PLATFORM_COMPONENTS}) == len(PLATFORM_COMPONENTS)


def test_layers_cover_every_unit_exactly_once():
    assert validate_inventory() == ()
    flattened = [key for _, keys in LAYERS for key in keys]
    assert len(flattened) == 32
