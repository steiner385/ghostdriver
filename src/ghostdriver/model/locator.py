"""Declarative element queries.

A Locator is the only durable way to refer to an element. Handles are
recycled by the OS and go void when a process exits, so resolution always
happens against a freshly enumerated tree (spec section 4.2).
"""

import shlex
from dataclasses import dataclass, asdict


@dataclass(frozen=True, slots=True)
class Locator:
    class_name: str | None = None
    text: str | None = None
    role: str | None = None
    within: "Locator | None" = None
    visible: bool | None = True
    index: int | None = None

    _KEYS = ("class", "text", "role", "visible", "index")

    def __post_init__(self) -> None:
        """Refuse an `index` on a scope, rather than ignoring it.

        Resolution applies `index` to the final match list. Ancestor
        matching asks a different question -- "is any ancestor like this?"
        -- and has no ordered list to index into, so an `index` inside
        `within` had no effect at all. It failed silently and in the worst
        direction: scoping to `within=Locator(class_name="Tab", index=99)`
        returned *every* match rather than none, so a locator that reads as
        precise resolved broadly with nothing to warn the caller.

        Refusing it follows what `parse` already does with `role`: a
        predicate that cannot mean what it appears to mean is an error, not
        a silent no-op. Nesting is covered transitively, since every
        `within` is itself a Locator that ran this check when it was built.
        """
        if self.within is not None and self.within.index is not None:
            raise ValueError(
                "index= is not usable inside within=: a scope has no "
                "ordered match list to index into, so it would be silently "
                "ignored. Put index= on the outer locator to choose among "
                "its matches, or identify the ancestor by class/text."
            )

    @classmethod
    def parse(cls, expr: str) -> "Locator":
        """Parse `class=X text="y" visible=false index=0`.

        `within` is not expressible in this shorthand; build it in code or
        via from_dict(). Values may be quoted with shlex rules.

        `role` is rejected rather than accepted. The field exists on the
        dataclass for profiles to populate, but Iteration 1 has no role
        mapping, so resolution matches nothing for a role predicate.
        Accepting it here would turn a typo-free query into an unexplained
        zero-match; refusing it says why.
        """
        fields: dict[str, object] = {}
        for token in shlex.split(expr):
            if "=" not in token:
                raise ValueError(f"malformed locator token: {token!r}")
            key, _, value = token.partition("=")
            if key not in cls._KEYS:
                raise ValueError(f"unknown locator key: {key!r}")
            if key == "role":
                raise ValueError(
                    "locator key 'role' is not usable yet: role mapping "
                    "arrives in a later iteration, so a role predicate "
                    "would match nothing rather than fail. Select on "
                    "class= or text= instead."
                )
            if key == "class":
                fields["class_name"] = value
            elif key == "visible":
                fields["visible"] = value.strip().lower() in ("1", "true", "yes")
            elif key == "index":
                fields["index"] = int(value)
            else:
                fields[key] = value
        return cls(**fields)  # type: ignore[arg-type]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Locator":
        data = dict(data)
        within = data.pop("within", None)
        return cls(within=cls.from_dict(within) if within else None, **data)

    def describe(self) -> str:
        """Human-readable form, for error messages."""
        parts = []
        if self.class_name:
            parts.append(f"class={self.class_name}")
        if self.text:
            parts.append(f'text="{self.text}"')
        if self.role:
            parts.append(f"role={self.role}")
        if self.visible is not None:
            parts.append(f"visible={str(self.visible).lower()}")
        if self.index is not None:
            parts.append(f"index={self.index}")
        if self.within:
            parts.append(f"within({self.within.describe()})")
        return " ".join(parts) or "<empty locator>"
