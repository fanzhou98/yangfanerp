"""Compatibility entry for the explicit, backed-up kilogram conversion.

Implementation and execution history belong to the unified migration registry.
The caller owns the IMMEDIATE transaction and its commit or rollback.
"""

def migrate(c,now,audit):
    import migrations
    return migrations.run_manual(c, '900-billing-kilograms', context={'now':now,'audit':audit})
