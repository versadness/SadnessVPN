import threading
import unittest
from engine.reconnect import Reconnector


class ReconnectTests(unittest.TestCase):
    def test_bounded_retries(self):
        calls=[]
        recovery=Reconnector(lambda: calls.append(1) or False,lambda:'off',lambda:True,calls.append,delays=(0,0,0))
        recovery.start();recovery.worker.join(2)
        self.assertEqual(calls.count(1),3)
        self.assertIn('трёх попыток',calls[-1])

    def test_manual_cancel_during_wait(self):
        calls=[]
        recovery=Reconnector(lambda: calls.append(1),lambda:'off',lambda:True,calls.append,delays=(10,))
        recovery.start();recovery.cancel();recovery.worker.join(1)
        self.assertFalse(recovery.worker.is_alive())
        self.assertEqual(calls,[])

    def test_disabled_does_not_start(self):
        recovery=Reconnector(lambda:False,lambda:'off',lambda:False,lambda _:None)
        recovery.start();self.assertIsNone(recovery.worker)

    def test_new_connection_is_not_interrupted(self):
        calls=[]
        recovery=Reconnector(lambda:calls.append(1),lambda:'on',lambda:True,calls.append,delays=(0,))
        recovery.start();recovery.worker.join(1);self.assertEqual(calls,[])

    def test_success_stops_retrying(self):
        state=['off'];calls=[]
        def connect():
            calls.append(1);state[0]='on';return True
        recovery=Reconnector(connect,lambda:state[0],lambda:True,lambda _:None,delays=(0,0,0))
        recovery.start();recovery.worker.join(2);self.assertEqual(calls,[1])
