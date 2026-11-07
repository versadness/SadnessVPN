"""Fault-injection checks for data loss and malformed update requests."""
import copy
import tempfile
import unittest
import zlib
from unittest import mock

from engine.subscriptions import SubscriptionError, _decompress
from engine.updates import UpdateManager
from engine.mihomo import MihomoManager
from ui import profile_state, server


class SubscriptionIntegrityTests(unittest.TestCase):
    def test_truncated_deflate_cannot_replace_a_subscription_with_partial_data(self):
        payload = b'trojan://password@example.invalid:443#Server\n' * 20
        compressed = zlib.compress(payload)
        self.assertEqual(_decompress(compressed, 'deflate'), payload)
        for cut in (1, 4, 15):
            with self.subTest(cut=cut), self.assertRaises(SubscriptionError):
                _decompress(compressed[:-cut], 'deflate')


class UpdateChannelValidationTests(unittest.TestCase):
    def test_non_string_channels_are_rejected_before_changing_state_or_starting_io(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager(directory)
            for value in ([], {}, True, 12):
                with self.subTest(value=value), mock.patch('engine.updates.threading.Thread') as thread:
                    with self.assertRaises(ValueError):
                        manager.check(channel=value)
                    self.assertEqual(manager.state['status'], 'idle')
                    self.assertEqual(manager.state['channel'], 'beta')
                    thread.assert_not_called()


class RoutingPersistenceTests(unittest.TestCase):
    def test_failed_routing_writes_leave_runtime_config_and_notifications_unchanged(self):
        original = {
            'mode': 'all',
            'apps': [{'exe': 'browser.exe', 'name': 'Browser', 'enabled': True}],
            'rules': [],
        }
        cases = [
            ('mode', {'mode': 'whitelist'}),
            ('add', {'exe': 'chat.exe', 'name': 'Chat'}),
            ('rename', {'exe': 'browser.exe', 'name': 'New name'}),
            ('remove', {'exe': 'browser.exe'}),
            ('toggle', {'exe': 'browser.exe', 'enabled': False}),
        ]
        for endpoint, data in cases:
            with (
                self.subTest(endpoint=endpoint),
                mock.patch.object(profile_state, 'apps_config', copy.deepcopy(original)),
                mock.patch.object(server, 'save_apps', side_effect=OSError('disk full')),
                mock.patch.object(server, '_broadcast') as broadcast,
                mock.patch.object(server, '_stopping', False),
                mock.patch.object(server._connection, '_state', 'off'),
            ):
                response = server.app.test_client().post('/api/apps/' + endpoint, json=data)
                self.assertEqual(profile_state.apps_config, original)
                self.assertEqual(response.status_code, 500)
                self.assertFalse(response.get_json()['ok'])
                broadcast.assert_not_called()


class PortReservationTests(unittest.TestCase):
    def test_refused_connections_do_not_mark_a_windows_reserved_port_as_available(self):
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        sock.connect_ex.return_value = 10061
        sock.bind.side_effect = PermissionError('port reserved')
        with mock.patch('engine.mihomo.socket.socket', return_value=sock):
            self.assertFalse(MihomoManager()._port_free(50000))

    def test_loopback_allocator_retries_when_tcp_cannot_bind_a_udp_port(self):
        from tools.loopback_ports import free_port
        sockets = [mock.MagicMock() for _ in range(4)]
        for sock in sockets:
            sock.__enter__.return_value = sock
        sockets[0].getsockname.return_value = ('127.0.0.1', 40000)
        sockets[1].bind.side_effect = PermissionError('TCP port reserved')
        sockets[2].getsockname.return_value = ('127.0.0.1', 40001)
        with mock.patch('tools.loopback_ports.socket.socket', side_effect=sockets):
            self.assertEqual(free_port(), 40001)


class ProfileRenamePersistenceTests(unittest.TestCase):
    def test_failed_group_renames_preserve_both_proxy_and_wireguard_names(self):
        for wireguard in (False, True):
            attr = 'wg_groups' if wireguard else 'groups'
            save = 'save_wireguard_groups' if wireguard else 'save_proxy_groups'
            prefix = '/api/wg' if wireguard else '/api'
            original = [{'id': 'g', 'name': 'Original', 'servers': []}]
            with (
                self.subTest(wireguard=wireguard),
                mock.patch.object(profile_state, attr, copy.deepcopy(original)),
                mock.patch.object(profile_state, save, side_effect=OSError('disk full')),
                mock.patch.object(server._connection, '_state', 'off'),
            ):
                response = server.app.test_client().post(
                    prefix + '/groups/rename', json={'id': 'g', 'name': 'Changed'})
                self.assertEqual(getattr(profile_state, attr), original)
                self.assertEqual(response.status_code, 500)
                self.assertFalse(response.get_json()['ok'])
