import tempfile
import time
import unittest
from pathlib import Path

import test_workflow as fixture
import auth
import collaboration
import erp_access

erp = fixture.erp


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.old = erp.DB
        self.temp = tempfile.TemporaryDirectory()
        erp.DB = Path(self.temp.name) / 'collaboration.db'
        erp.init_db(demo=False)
        with erp.connect(True) as c:
            self.admin = auth.create_initial_admin(c, 'admin', '管理员', 'AdminPassword123!', int(time.time()), audit=erp.audit)
            self.worker = auth.create_user(c, self.admin, {'username': 'worker', 'display_name': '库管甲', 'role': '库管', 'password': 'WorkerPassword123!'}, int(time.time()), audit=erp.audit)
            self.director = auth.create_user(c, self.admin, {'username': 'director', 'display_name': '厂长乙', 'role': '厂长', 'password': 'DirectorPassword123!'}, int(time.time()), audit=erp.audit)

    def tearDown(self):
        erp.DB = self.old
        self.temp.cleanup()

    def test_direct_chat_idempotency_unread_and_read_cursor(self):
        with erp.connect(True) as c:
            thread = collaboration.create_thread(c, self.worker, {'kind': 'direct', 'user_id': self.director['id']}, erp.now, erp.audit)
            self.assertEqual(thread['kind'], 'direct')
            same = collaboration.create_thread(c, self.director, {'kind': 'direct', 'user_id': self.worker['id']}, erp.now, erp.audit)
            self.assertEqual(same['id'], thread['id'])
            body = {'thread_id': thread['id'], 'body': '今晚这批豆子从豆腐库和豆皮库各上一半', 'request_key': 'chat-test-1'}
            first = collaboration.send(c, self.worker, body, erp.now, erp.audit)
            retry = collaboration.send(c, self.worker, body, erp.now, erp.audit)
            self.assertEqual(first['message']['id'], retry['message']['id'])
            with self.assertRaises(auth.AuthError):
                collaboration.messages(c, self.admin, thread['id'], 0)
            inbox = collaboration.list_notifications(c, self.director)
            self.assertEqual(inbox['unread_count'], 1)
            self.assertEqual(inbox['items'][0]['kind'], 'chat')
            self.assertEqual(inbox['items'][0]['thread_id'], thread['id'])
            messages = collaboration.messages(c, self.director, thread['id'], 0)
            self.assertEqual(messages['messages'][0]['body'], body['body'])
            read = collaboration.read_thread(c, self.director, {'thread_id': thread['id'], 'last_seq': first['message']['seq']})
            self.assertEqual(read['unread_count'], 0)
            self.assertEqual(collaboration.list_notifications(c, self.director)['unread_count'], 0)
            listed = collaboration.list_threads(c, self.director)
            self.assertEqual(next(t for t in listed['threads'] if t['id'] == thread['id'])['unread_count'], 0)
            self.assertTrue(any(t['id'] == collaboration.GROUP_ALL for t in listed['threads']))

    def test_group_chat_requires_members_and_notifies_everyone(self):
        with erp.connect(True) as c:
            thread = collaboration.create_thread(c, self.worker, {'kind': 'group', 'title': '夜班交接', 'user_ids': [self.director['id'], self.admin['id']], 'request_key': 'group-test-1'}, erp.now, erp.audit)
            self.assertEqual(thread['member_count'], 3)
            self.assertEqual(thread['title'], '夜班交接')
            with self.assertRaises(ValueError):
                collaboration.create_thread(c, self.worker, {'kind': 'group', 'title': '空群', 'user_ids': [], 'request_key': 'group-test-2'}, erp.now, erp.audit)
            collaboration.send(c, self.director, {'thread_id': thread['id'], 'body': '明早六点前完成交接', 'request_key': 'group-msg-1'}, erp.now, erp.audit)
            self.assertEqual(collaboration.list_notifications(c, self.worker)['unread_count'], 1)
            self.assertEqual(collaboration.list_notifications(c, self.admin)['unread_count'], 1)

    def test_feedback_admin_reply_status_and_owner_follow_up(self):
        with erp.connect(True) as c:
            ticket = collaboration.create_feedback(c, self.worker, {'category': '功能异常', 'title': '上豆登记看不到', 'body': '保存后列表没有刷新，请协助检查', 'request_key': 'feedback-1'}, erp.now, erp.audit)
            self.assertEqual(ticket['status'], 'open')
            admin_inbox = collaboration.list_feedback(c, self.admin)
            self.assertTrue(admin_inbox['can_manage'])
            self.assertEqual(admin_inbox['tickets'][0]['id'], ticket['id'])
            self.assertEqual(collaboration.list_notifications(c, self.admin)['unread_count'], 1)
            self.assertEqual(collaboration.list_feedback(c, self.director)['tickets'], [])
            with self.assertRaises(auth.AuthError):
                collaboration.reply_feedback(c, self.director, {'id': ticket['id'], 'version': ticket['version'], 'body': '越权回复'}, erp.now, erp.audit)
            replied = collaboration.reply_feedback(c, self.admin, {'id': ticket['id'], 'version': ticket['version'], 'body': '已定位，请重新打开页面查看', 'status': 'replied'}, erp.now, erp.audit)
            self.assertEqual(replied['status'], 'replied')
            self.assertEqual(len(replied['replies']), 1)
            self.assertEqual(collaboration.list_notifications(c, self.worker)['unread_count'], 1)
            follow = collaboration.reply_feedback(c, self.worker, {'id': ticket['id'], 'version': replied['version'], 'body': '已经看到了，谢谢'}, erp.now, erp.audit)
            self.assertEqual(follow['status'], 'open')
            closed = collaboration.reply_feedback(c, self.admin, {'id': ticket['id'], 'version': follow['version'], 'status': 'closed'}, erp.now, erp.audit)
            self.assertEqual(closed['status'], 'closed')
            with self.assertRaises(ValueError):
                collaboration.reply_feedback(c, self.admin, {'id': ticket['id'], 'version': ticket['version'], 'status': 'replied'}, erp.now, erp.audit)

    def test_collaboration_menus_default_for_every_role(self):
        for role in ('库管', '会计', '出纳', '厂长', '物流负责人', '司机', '老板', '管理员'):
            modules = erp_access.defaults(role)['modules']
            self.assertIn('workspace.chat', modules, role)
            self.assertIn('system.feedback', modules, role)

    def test_feedback_retry_cannot_return_another_users_ticket_or_replies(self):
        with erp.connect(True) as c:
            body = {'category': '功能异常', 'title': '反馈权限核验', 'body': '检查跨账号重复提交的返回内容', 'request_key': 'feedback-shared-key'}
            ticket = collaboration.create_feedback(c, self.worker, body, erp.now, erp.audit)
            replied = collaboration.reply_feedback(c, self.admin,
                {'id': ticket['id'], 'version': ticket['version'], 'body': '仅反馈提交人可查看这条回复'}, erp.now, erp.audit)
            before = c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0]
            with self.assertRaises(auth.AuthError) as denied:
                collaboration.create_feedback(c, self.director, body, erp.now, erp.audit)
            self.assertEqual(denied.exception.status, 403)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM feedback_tickets').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], before)
            retry = collaboration.create_feedback(c, self.worker, body, erp.now, erp.audit)
            self.assertEqual(retry, replied)

    def test_message_retry_is_owned_by_its_sender_even_in_shared_thread(self):
        with erp.connect(True) as c:
            body = {'thread_id': collaboration.GROUP_ALL, 'body': '检查群内跨账号重复提交', 'request_key': 'message-shared-key'}
            sent = collaboration.send(c, self.worker, body, erp.now, erp.audit)
            before = c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0]
            with self.assertRaises(auth.AuthError) as denied:
                collaboration.send(c, self.director, body, erp.now, erp.audit)
            self.assertEqual(denied.exception.status, 403)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], before)
            self.assertEqual(collaboration.send(c, self.worker, body, erp.now, erp.audit)['message']['id'], sent['message']['id'])

    def test_group_retry_is_owned_by_its_creator_even_if_both_are_members(self):
        with erp.connect(True) as c:
            body = {'kind': 'group', 'title': '重复提交权限核验', 'user_ids': [self.worker['id'], self.director['id']], 'request_key': 'group-shared-key'}
            group = collaboration.create_thread(c, self.worker, body, erp.now, erp.audit)
            with self.assertRaises(auth.AuthError) as denied:
                collaboration.create_thread(c, self.director, body, erp.now, erp.audit)
            self.assertEqual(denied.exception.status, 403)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM chat_threads WHERE id<>'GROUP-ALL'").fetchone()[0], 1)
            self.assertEqual(collaboration.create_thread(c, self.worker, body, erp.now, erp.audit)['id'], group['id'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
