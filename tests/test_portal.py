import unittest
from unittest.mock import Mock,patch
from tempfile import TemporaryDirectory
from pension_tool.portal import Portal,DOCS,PAYMENTS

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
        self.portal.wait_ready=Mock()
        with self.assertRaisesRegex(RuntimeError,'menu link not found'):self.portal.navigate(PAYMENTS)
        self.portal.page.goto.assert_not_called()

    def test_expanded_branch_is_not_closed(self):
        parent=Mock();child=Mock();child.count.return_value=1;child.is_visible.return_value=True
        self.portal.wait_menu=Mock()
        self.portal.open_menu_branch(parent,child,'Reports')
        parent.evaluate.assert_not_called()
    def test_collapsed_branch_waits_for_child_after_click(self):
        parent=Mock();child=Mock();child.count.return_value=1;child.is_visible.return_value=False
        self.portal.wait_menu=Mock()
        self.portal.open_menu_branch(parent,child,'Reports')
        parent.evaluate.assert_called_once()
        self.assertEqual(self.portal.wait_menu.call_args_list[-1].args,(child,'Submenu after Reports'))
    def test_hidden_menu_timeout_does_not_skip_case(self):
        item=Mock();item.count.return_value=0
        with patch('pension_tool.portal.time.monotonic',side_effect=[0,91]):
            with self.assertRaisesRegex(RuntimeError,'case was not skipped'):self.portal.wait_menu(item,'Reports')

    def test_document_url_does_not_require_download_word(self):
        link=Mock();link.get_attribute.return_value='/documents/sanction.pdf'
        self.portal.pdf=Mock(return_value='verified.pdf')
        self.assertEqual(self.portal.document_link(link,'revision.pdf'),'verified.pdf')
        self.portal.pdf.assert_called_once_with('https://dotpension.gov.in/documents/sanction.pdf','revision.pdf')
