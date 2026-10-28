import unittest
import uuid
import company
import statements
import byproduct_accounts
import test_statement_documents as statements_fixture
import test_byproduct_accounts as byproduct_fixture

erp=statements_fixture.erp


def configure(name):
    with erp.connect(True) as c:
        return company.save(c,{'name':name,'phone':'TEST-PHONE','address':'合成测试地址','version':company.current(c)['version'],'request_key':str(uuid.uuid4())},'管理员',erp.now,erp.audit)


class CustomerCompanyTests(unittest.TestCase):
    setUp=statements_fixture.StatementDocumentTests.setUp
    tearDown=statements_fixture.StatementDocumentTests.tearDown
    order=statements_fixture.StatementDocumentTests.order
    settle=statements_fixture.StatementDocumentTests.settle
    review=statements_fixture.StatementDocumentTests.review
    body=statements_fixture.StatementDocumentTests.body
    issue=statements_fixture.StatementDocumentTests.issue

    def test_company_snapshots_and_retry_and_stale_preview(self):
        self.review(self.settle(self.order()));configure('合成公司甲')
        body={**self.body(),'seller_name':'合成公司甲','seller_phone':'TEST-PHONE'}
        issued=self.issue(body);self.assertEqual(issued['company']['name'],'合成公司甲')
        self.assertIn('合成测试地址',issued['wechat_text'])
        configure('合成公司乙');self.assertEqual(self.issue(body),issued)
        with erp.connect() as c:self.assertEqual(statements.get_document(c,issued['document_id']),issued)
        with self.assertRaisesRegex(ValueError,'公司信息'):self.issue({**body,'request_key':str(uuid.uuid4())})


class ByproductCompanyTests(unittest.TestCase):
    setUp=byproduct_fixture.ByproductAccountsTests.setUp
    tearDown=byproduct_fixture.ByproductAccountsTests.tearDown
    client=byproduct_fixture.ByproductAccountsTests.client
    sale=byproduct_fixture.ByproductAccountsTests.sale
    preview=byproduct_fixture.ByproductAccountsTests.preview
    body=byproduct_fixture.ByproductAccountsTests.body
    issue=byproduct_fixture.ByproductAccountsTests.issue

    def test_byproduct_issuer_is_frozen(self):
        cid=self.client();self.sale(cid);configure('合成公司甲')
        preview=self.preview(cid);self.assertEqual(preview['issuer_profile']['name'],'合成公司甲')
        body={**self.body(preview),'seller_name':'合成公司甲','seller_phone':'TEST-PHONE'}
        issued=self.issue(body);configure('合成公司乙')
        self.assertEqual(self.issue(body),issued)
        with erp.connect() as c:self.assertEqual(byproduct_accounts.get_document(c,issued['document_id'])['company']['name'],'合成公司甲')
        with self.assertRaisesRegex(ValueError,'公司信息'):self.issue({**body,'request_key':str(uuid.uuid4())})


if __name__=='__main__':unittest.main()
