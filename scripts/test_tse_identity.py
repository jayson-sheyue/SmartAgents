# -*- coding: utf-8 -*-
"""Unit tests for TSE identity / data ACL helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from smart_agents.tse_identity import (
    assert_item_access,
    enforce_data_scope,
    enforce_owner_scope,
    format_principal_instruction_block,
    resolve_tse_principal,
    row_visible_to,
)


def _ctx(*, email: str = "", source: str = "") -> SimpleNamespace:
    state: dict = {}
    if email:
        state["tse_user_email"] = email
    if source:
        state["tse_auth_source"] = source
    return SimpleNamespace(state=state)


class TseIdentityTests(unittest.TestCase):
    def test_unscoped_without_state(self):
        p = resolve_tse_principal(None)
        self.assertFalse(p["scoped"])
        self.assertEqual(p["email"], "")

    def test_scoped_tse_app(self):
        p = resolve_tse_principal(_ctx(email="a@x.com", source="tse_app"))
        self.assertTrue(p["scoped"])
        self.assertEqual(p["email"], "a@x.com")

    def test_email_without_tse_app_source_not_scoped(self):
        p = resolve_tse_principal(_ctx(email="a@x.com", source="playground"))
        self.assertFalse(p["scoped"])

    def test_enforce_cross_user_forbidden(self):
        ctx = _ctx(email="me@x.com", source="tse_app")
        owner, access, err = enforce_data_scope(
            ctx, requested_owner_email="other@x.com"
        )
        self.assertIsNotNone(err)
        self.assertEqual(err["error"]["code"], "CROSS_USER_FORBIDDEN")
        self.assertEqual(access, "me@x.com")

    def test_enforce_forces_access_email(self):
        ctx = _ctx(email="me@x.com", source="tse_app")
        owner, access, err = enforce_data_scope(ctx, requested_owner_email="")
        self.assertIsNone(err)
        self.assertEqual(owner, "")
        self.assertEqual(access, "me@x.com")

    def test_enforce_owner_scope_defaults_to_self(self):
        ctx = _ctx(email="me@x.com", source="tse_app")
        owner, err = enforce_owner_scope(ctx, "")
        self.assertIsNone(err)
        self.assertEqual(owner, "me@x.com")

    def test_row_visible_owner_and_viewer(self):
        self.assertTrue(row_visible_to("me@x.com", [], "me@x.com"))
        self.assertTrue(row_visible_to("boss@x.com", ["me@x.com"], "me@x.com"))
        self.assertFalse(row_visible_to("boss@x.com", ["other@x.com"], "me@x.com"))

    def test_assert_item_access_denied(self):
        ctx = _ctx(email="me@x.com", source="tse_app")
        denied = assert_item_access(
            ctx, owner="other@x.com", viewers=[], item_id="c1"
        )
        self.assertIsNotNone(denied)
        self.assertEqual(denied["error"]["code"], "ITEM_ACCESS_DENIED")

    def test_assert_item_access_shared_ok(self):
        ctx = _ctx(email="me@x.com", source="tse_app")
        denied = assert_item_access(
            ctx, owner="other@x.com", viewers=["me@x.com"], item_id="c1"
        )
        self.assertIsNone(denied)

    def test_instruction_block_mentions_email(self):
        ctx = _ctx(email="me@x.com", source="tse_app")
        block = format_principal_instruction_block(ctx)
        self.assertIn("me@x.com", block)
        self.assertIn("强制", block)


if __name__ == "__main__":
    unittest.main()
