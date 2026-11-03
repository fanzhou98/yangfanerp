"""Cross-account retry boundaries over authenticated HTTP, using temporary data."""
import unittest

import test_auth_http as fixture


class CollaborationRequestKeyHTTPTests(unittest.TestCase):
    initial_password = fixture.AuthHTTPTests.initial_password
    personal_password = fixture.AuthHTTPTests.personal_password
    setUp = fixture.AuthHTTPTests.setUp
    tearDown = fixture.AuthHTTPTests.tearDown
    user = fixture.AuthHTTPTests.user

    def test_another_account_cannot_reuse_feedback_request_key(self):
        worker, worker_user = self.user('retryworker', '库管')
        director, director_user = self.user('retrydirector', '厂长')
        feedback = {'category': '功能异常', 'title': '跨账号重试', 'body': '其他账号不可复用提交编号读取回复', 'request_key': 'http-shared-feedback'}
        code, ticket, _ = worker.request('/api/feedback', feedback)
        self.assertEqual(code, 200, ticket)
        code, replied, _ = self.admin.request('/api/feedback/reply',
            {'id': ticket['id'], 'version': ticket['version'], 'body': '应只对原反馈人可见的回复'})
        self.assertEqual(code, 200, replied)
        code, denied, _ = director.request('/api/feedback', feedback)
        self.assertEqual(code, 403, denied)
        self.assertNotIn('replies', denied)
        code, retried, _ = worker.request('/api/feedback', feedback)
        self.assertEqual(code, 200, retried)
        self.assertEqual(retried['id'], ticket['id'])
        self.assertEqual(retried['replies'], replied['replies'])
        code, history, _ = worker.request('/api/feedback?page=1&page_size=1')
        self.assertEqual(code, 200, history)
        self.assertEqual(history['page'], 1)
        self.assertEqual(history['page_size'], 1)
        self.assertEqual(history['total'], 1)
        self.assertEqual(history['tickets'][0]['id'], ticket['id'])
        code, hidden, _ = director.request('/api/feedback?search=not-a-title')
        self.assertEqual(code, 200, hidden)
        self.assertEqual(hidden['total'], 0)
        code, invalid, _ = worker.request('/api/feedback?page=0')
        self.assertEqual(code, 400, invalid)



if __name__ == '__main__':
    unittest.main(verbosity=2)
