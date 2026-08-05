"""CSV-export ingestion package.

``OuraParser`` is re-exported lazily (PEP 562): importing submodules like
``key_migration`` must not drag in the parser's pandas dependency, which the
slim server image does not install.
"""


def __getattr__(name):
    if name == "OuraParser":
        from .manager import OuraParser

        return OuraParser
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
