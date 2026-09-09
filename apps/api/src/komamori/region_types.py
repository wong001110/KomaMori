from __future__ import annotations

# Automatic detection is intentionally unclassified. Destructive processing is
# opt-in through a known semantic type rather than opt-out from SFX.
CLEANABLE_REGION_TYPES = frozenset({
    "dialogue",
    "thought",
    "narration",
    "caption",
    "sign",
    "ui",
})

TRANSLATABLE_REGION_TYPES = CLEANABLE_REGION_TYPES

SAFE_UNCLASSIFIED_REGION_TYPES = frozenset({"unknown", "sfx"})
