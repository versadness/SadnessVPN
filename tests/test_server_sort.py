import unittest

from engine.server_sort import sort_servers_by_ping


class ServerSortTests(unittest.TestCase):
    def test_sorts_reachable_servers_and_preserves_selected_object(self):
        slow = {"remark": "slow"}
        missing = {"remark": "missing"}
        fast = {"remark": "fast"}

        ordered, selected = sort_servers_by_ping(
            [slow, missing, fast],
            {0: 240, 1: None, 2: 35},
            selected_index=0,
        )

        self.assertEqual(ordered, [fast, slow, missing])
        self.assertEqual(selected, 1)
        self.assertIs(ordered[selected], slow)

    def test_equal_and_missing_results_keep_stable_order(self):
        servers = [{"remark": str(index)} for index in range(4)]

        ordered, _selected = sort_servers_by_ping(
            servers,
            {0: 50, 1: None, 2: 50},
        )

        self.assertEqual(ordered, [servers[0], servers[2], servers[1], servers[3]])


if __name__ == "__main__":
    unittest.main()
