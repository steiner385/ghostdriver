"""Declarative element queries.

A Locator is the only durable way to refer to an element. Handles are
recycled by the OS and go void when a process exits, so resolution always
happens against a freshly enumerated tree (spec section 4.2).
"""

import shlex
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class Locator:
    class_name: str | None = None
    text: str | None = None
    role: str | None = None
    within: "Locator | None" = None
    visible: bool | None = True
    index: int | None = None

    _KEYS = ("class", "text", "role", "visible", "index")
    _WITHIN = "within=("

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
    def _split_within(cls, expr: str) -> tuple[str, "Locator | None"]:
        """Pull a `within=(...)` group out of `expr`, if there is one.

        Scanning for the balanced closing paren rather than splitting on
        one, because a caption can contain a bracket -- `text="Save (all)"`
        is an ordinary button -- and quotes have to be respected while
        counting depth or that button breaks the parse.
        """
        start = expr.find(cls._WITHIN)
        if start == -1:
            return expr, None

        opened = start + len(cls._WITHIN)
        depth, quote, index = 1, "", opened
        while index < len(expr):
            char = expr[index]
            if quote:
                if char == quote:
                    quote = ""
            elif char in "\"'":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        if depth != 0:
            raise ValueError(
                f"unbalanced within=( in locator {expr!r}: no closing paren"
            )
        inner = expr[opened:index]
        if not inner.strip():
            raise ValueError("within=() is empty; name the ancestor")
        return expr[:start] + expr[index + 1:], cls.parse(inner)

    @classmethod
    def parse(cls, expr: str) -> "Locator":
        """Parse `class=X text="y" visible=false index=0`.

        `within=(...)` scopes to a matching ancestor and nests, so
        `within=(class=Tab within=(class=Frame))` is legal. It is expressible
        here rather than only in code because scoping by ancestor is how two
        identically-captioned controls are told apart on this class of
        target -- the same caption at the same offset on two pages -- and a
        caller reaching this through a tool can only send a string. Values
        may be quoted with shlex rules.

        `role` is rejected rather than accepted. The field exists on the
        dataclass for profiles to populate, but Iteration 1 has no role
        mapping, so resolution matches nothing for a role predicate.
        Accepting it here would turn a typo-free query into an unexplained
        zero-match; refusing it says why.
        """
        expr, scope = cls._split_within(expr)
        fields: dict[str, object] = {}
        if scope is not None:
            fields["within"] = scope
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
            # The same syntax `parse` accepts, so a described locator can be
            # handed straight back to it -- error messages quote locators,
            # and one that cannot be copied out of a message is friction.
            parts.append(f"within=({self.within.describe()})")
        return " ".join(parts) or "<empty locator>"
