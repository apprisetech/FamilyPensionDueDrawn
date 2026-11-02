import unittest
from unittest.mock import Mock,patch
from tempfile import TemporaryDirectory
from pension_tool.portal import Portal,DOCS

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
    def test_loading_timeout_is_not_skip(self):
        with patch('pension_tool.portal.time.monotonic',side_effect=[0,91]):
            with self.assertRaisesRegex(RuntimeError,'Case was not skipped'):self.portal.wait_ready('predicate','Report loading')
    def test_missing_menu_never_opens_direct_url(self):
        self.portal.page.url='https://dotpension.gov.in/Home'
        with self.assertRaisesRegex(RuntimeError,'menu link not found'):self.portal.navigate(DOCS)
        self.portal.page.goto.assert_not_called()
