import copy
from html.parser import HTMLParser
import unittest
import payroll
import test_payroll as fixture


class Parser(HTMLParser):
    def __init__(self):super().__init__();self.scripts=[];self.rows=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script':self.scripts.append(attrs.get('src'))
        if tag=='tr' and 'data-print-row-key' in attrs:self.rows.append(attrs['data-print-row-key'])


class PayrollPrintTests(unittest.TestCase):
    setUp=fixture.PayrollTests.setUp
    tearDown=fixture.PayrollTests.tearDown

    def test_company_name_only_and_shared_component(self):
        report=payroll.report(self.c,'2020-09');report['company']={'name':'合成公司抬头','phone':'PHONE-PRIVATE','address':'ADDRESS-PRIVATE','tax_id':'TAX-PRIVATE','contact':'CONTACT-PRIVATE'}
        html=payroll.print_html(report,{},True)
        self.assertIn('合成公司抬头',html)
        for value in ('PHONE-PRIVATE','ADDRESS-PRIVATE','TAX-PRIVATE','CONTACT-PRIVATE'):self.assertNotIn(value,html)
        parsed=Parser();parsed.feed(html);self.assertEqual(parsed.scripts,['/print.js']);self.assertEqual(parsed.rows,[self.employee['id']])
        self.assertIn('data-print-key="signature"',html);self.assertIn('data-print-money-columns="net,paid"',html)

    def test_print_filter_and_snapshot_are_read_only(self):
        report=payroll.report(self.c,'2020-09');before=copy.deepcopy(report)
        html=payroll.print_html(report,{'search':['没有这个员工']},True);parsed=Parser();parsed.feed(html);self.assertEqual(parsed.rows,[])
        self.assertEqual(report,before)
        attendance=payroll.print_html(report,{},False);self.assertIn('月度考勤表',attendance);self.assertNotIn('data-print-key="bank_card"',attendance)

    def test_names_and_adjustment_notes_cannot_insert_html(self):
        report=payroll.report(self.c,'2020-09');report['rows'][0]['employee_name']='甲<script>alert(1)</script>'
        report['rows'][0]['reason']='"><img src=x onerror=alert(1)>'
        html=payroll.print_html(report,{},True);parsed=Parser();parsed.feed(html)
        self.assertEqual(parsed.scripts,['/print.js']);self.assertIn('&lt;script&gt;',html);self.assertIn('&lt;img',html)


if __name__=='__main__':unittest.main()
