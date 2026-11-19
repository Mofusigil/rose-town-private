import copy
import pathlib
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import private_server as server


class ShopGatewayTests(unittest.TestCase):
    def setUp(self):
        self.original = copy.deepcopy(server.PLAYER_STATE)
        self.original_file = server.STATE_FILE
        self.directory = tempfile.TemporaryDirectory()
        server.STATE_FILE = str(pathlib.Path(self.directory.name) / "player.json")
        server.PLAYER_STATE.update(rosemoney=1000, balance=50, seeds={}, flowers={},
                                  pots=server._starter_pots(), experience=0, charm=0)

    def tearDown(self):
        server.PLAYER_STATE.clear()
        server.PLAYER_STATE.update(self.original)
        server.STATE_FILE = self.original_file
        self.directory.cleanup()

    def buy(self, seed, count, points=False):
        return server.handle_cmd(
            "rosary_qb_buy_seed" if points else "rosary0908_rosemoney_buy_seed",
            {"seedtype" if points else "type": str(seed), "count": str(count)})

    def test_coin_purchase_updates_inventory_and_reload(self):
        response = self.buy(26078, 1)  # 金彗星，配置价666金币。
        self.assertEqual(response["result"], 0)
        self.assertEqual((response["type"], response["count"]), (26078, 1))
        self.assertEqual(response["rosemoneyuse"], 666)
        self.assertEqual(response["rosemoneyleft"], 334)
        self.assertEqual(response["vegetableseed26078"], 1)
        initial = server.handle_cmd("rosary0909_get_init_first_self", {})
        self.assertEqual(initial["rosemoney"], 334)
        self.assertEqual(initial["vegetableseed26078"], 1)
        self.assertEqual(server._load_player_state(), server.PLAYER_STATE)

    def test_spending_all_coins_returns_zero(self):
        response = self.buy(127, 1)  # 风信子，1000金币。
        self.assertEqual(response["result"], 0)
        self.assertEqual(response["rosemoneyleft"], 0)

    def test_points_purchase_is_free_and_grants_exact_quantity(self):
        response = self.buy(26147, 2, points=True)  # 龙吐珠，每粒10点券。
        self.assertEqual(response["result"], 0)
        self.assertEqual(response["balance"], 50)
        self.assertTrue(response["local_free_pay"])
        self.assertEqual(response["rosemoneyleft"], 1000)
        self.assertEqual(response["count"], 2)
        self.assertEqual(server.handle_cmd("rosary_diamond", {})["balance"], 50)

    def test_invalid_requests_and_insufficient_funds_do_not_mutate(self):
        before = copy.deepcopy(server.PLAYER_STATE)
        for seed, count, points in [
            (999999, 1, False), (133, 0, False), (133, -1, False),
            (133, 100, False), (133, "NaN", False), (133, 1, True),
            (26147, 1, False), (26241, 1, False), (26147, 0, True),
        ]:
            with self.subTest(seed=seed, count=count, points=points):
                self.assertNotEqual(self.buy(seed, count, points)["result"], 0)
                self.assertEqual(server.PLAYER_STATE, before)

    def test_concurrent_purchases_do_not_overspend(self):
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.buy(133, 10), range(2)))
        self.assertEqual(sum(response["result"] == 0 for response in results), 1)
        self.assertEqual(server.PLAYER_STATE["rosemoney"], 400)
        self.assertEqual(server.PLAYER_STATE["seeds"][133], 10)

    def test_market_and_history_use_client_configuration(self):
        initial = server.handle_cmd("rosary0907_get_init_second", {})
        self.assertEqual(initial["PAInfo0"]["fp"]["vegetablefruit28078"], 85)
        self.assertGreater(initial["etime"], 0)
        response = server.handle_cmd("rosary_get_action_flowerinfo", {
            "history": "1", "fid": "28078"})
        self.assertEqual((response["fid"], response["pmin"], response["pmax"]),
                         (28078, 85, 85))


if __name__ == "__main__":
    unittest.main()
