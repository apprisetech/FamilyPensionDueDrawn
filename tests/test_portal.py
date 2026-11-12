import ast
import unittest
from pathlib import Path
from unittest.mock import Mock
from tempfile import TemporaryDirectory
from pension_tool.portal import Portal, DOCS, PAYMENTS


class PortalChecks(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.portal=Portal(self.temp.name);self.portal.page=Mock()
        self.portal.page.url=DOCS
        self.portal.page.locator.return_value.count.return_value=0

    def test_login_redirect_never_becomes_missing_document(self):
        self.portal.page.url='https://dotpension.gov.in/Login/Index'
        with self.assertRaisesRegex(RuntimeError,'Session expired'):self.portal.documents('123456789012345')
        self.portal.page.goto.assert_not_called()

    def test_slow_page_waits_until_ready(self):
        self.portal.page.evaluate.side_effect=[False,False,True]
        self.portal.wait_ready('predicate','Report loading')
        self.assertEqual(self.portal.page.wait_for_timeout.call_count,2)

    def test_loading_timeout_is_recorded_not_skipped(self):
        self.portal.timeout=0
        with self.assertRaisesRegex(RuntimeError,'case was not skipped'):self.portal.wait_ready('predicate','Report loading')
        self.portal.record.finish(RuntimeError('stopped'))
        self.assertTrue((self.portal.record.folder/'diagnostics.zip').exists())

    def test_public_home_is_expired_not_missing_report(self):
        self.portal.page.url='https://dotpension.gov.in/'
        with self.assertRaisesRegex(RuntimeError,'Session expired'):self.portal.navigate(PAYMENTS)
        self.portal.page.goto.assert_not_called()

    def test_expanded_branch_is_not_closed(self):
        parent=Mock();child=Mock();child.count.return_value=1;child.is_visible.return_value=True
        self.portal.wait_menu=Mock()
        self.portal.open_menu_branch(parent,child,'Reports')
        parent.click.assert_not_called()

    def test_collapsed_branch_uses_native_click_then_verifies_child(self):
        parent=Mock();parent.count.return_value=1
        child=Mock();child.count.return_value=1;child.is_visible.return_value=False
        self.portal.wait_menu=Mock()
        self.portal.open_menu_branch(parent,child,'Reports')
        parent.click.assert_called_once();parent.evaluate.assert_called_once_with('(el)=>el.tagName')
        self.assertEqual(self.portal.wait_menu.call_args_list[-1].args,(child,'Submenu after Reports'))

    def test_unknown_destination_cannot_open_direct_url(self):
        with self.assertRaisesRegex(ValueError,'Unknown report'):self.portal.navigate('https://dotpension.gov.in/unknown')
        self.portal.page.goto.assert_not_called()

    def test_production_collector_has_no_direct_navigation_or_request_fetch(self):
        path=Path(__file__).resolve().parents[1]/'pension_tool/portal.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        attrs=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertNotIn('goto',attrs)
        self.assertNotIn('pdf',attrs)
        source=path.read_text(encoding='utf-8')
        self.assertNotIn('context.request.',source)
        self.assertNotIn('el.click()',source)
        self.assertNotIn('removeAttribute("readonly")',source)
