"""SELECTIVE: behave honestly toward some neighbors, lie to others.

This is the hardest attack to detect from a single vantage point, because any
one honest neighbor only ever sees consistent behavior. Detection requires
*cross-source* comparison (two neighbors of the attacker disagree about what it
told them). SELECTIVE is a composition wrapper: it applies its inner attacks
only when the advertisement is destined for a victim neighbor, and passes the
honest advertisement through untouched for everyone else.
"""

from .base import Attack


class Selective(Attack):
    def __init__(self, victims, inner):
        """
        Args:
            victims: neighbors that receive the lies. Everyone else gets honesty.
            inner: list of :class:`Attack` applied (in order) to victims only.
        """
        self.victims = set(victims or [])
        self.inner = list(inner or [])

    def apply(self, advertisement, ctx):
        if ctx.recipient not in self.victims:
            return advertisement
        ad = advertisement
        for attack in self.inner:
            ad = attack.apply(ad, ctx)
        return ad

    def describe(self):
        inner = ", ".join(a.describe() for a in self.inner)
        return f"SELECTIVE(victims={sorted(self.victims)}, inner=[{inner}])"
