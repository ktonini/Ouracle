"""Decoders for history events read directly off the ring.

Ported from github.com/Th0rgal/open_oura (`crates/oura-protocol/src/events.rs`),
which recovered these layouts from the decompiled native parser.

Design: decoders are pure functions over the raw body and return ``None`` when
a body does not match the expected shape, so a questionable layout leaves the
event stored raw rather than silently producing wrong numbers. Raw bodies are
always kept, so everything can be re-decoded as decoders improve.
"""

from .decoders import decode_event, decode_name, EVENT_NAMES

__all__ = ["decode_event", "decode_name", "EVENT_NAMES"]
