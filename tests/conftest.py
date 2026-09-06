import sys

import pytest


@pytest.fixture
def clear_generated_modules():
    def clear():
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                sys.modules.pop(name, None)
            if name == "config" or name.startswith("config."):
                sys.modules.pop(name, None)

    clear()
    yield clear
    clear()
