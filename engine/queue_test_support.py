"""Shared engine fixture base; all production admission guards remain active.

Kept for existing test imports. Experimental mode exercises the real helpers,
without the former restricted-preview admission/capability mocks.
"""
from unittest import TestCase


class QueuePrimitiveFixture(TestCase):
    pass
