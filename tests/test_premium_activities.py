import copy
import datetime as dt
import pathlib
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import premium_activities as activities
import private_server as server


NOW = int(dt.datetime(2026, 10, 14, 12, tzinfo=activities.LOCAL_TIMEZONE).timestamp())


class PremiumActivityTests(unittest.TestCase):
    def setUp(self):
        self.original = copy.deepcopy(server.PLAYER_STATE)
        self.original_file = server.STATE_FILE
        self.directory = tempfile.TemporaryDirectory()
        server.STATE_FILE = str(pathlib.Path(self.directory.name) / "player.json")
        server.PLAYER_STATE.clear()
        server.PLAYER_STATE.update(server._load_player_state())
        self.clock = patch("premium_activities.time.time", return_value=NOW)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        server.PLAYER_STATE.clear()
        server.PLAYER_STATE.update(self.original)
        server.STATE_FILE = self.original_file
        self.directory.cleanup()

    def activity(self, cmd, **params):
        return server.handle_cmd("rosary_activity_oper", {"cmd": str(cmd), **params})

    def assert_free(self, result):
        self.assertEqual(result["result"], 0, result)
        self.assertEqual(result["balance"], 0)
        self.assertEqual(result["cost"], 0)
        self.assertEqual(result["pay_count"], 0)
        self.assertEqual(server.PLAYER_STATE["balance"], 0)

    def assert_saved(self):
        self.assertEqual(server._load_player_state(), server.PLAYER_STATE)

    def test_monthly_init_and_purchase_return_complete_client_cards(self):
        initial = self.activity(43, action="1")
        self.assert_free(initial)
        self.assertEqual(len(initial["cards"]), 7)
        self.assertTrue(all(card["days"] == [] for card in initial["cards"]))
        for identifier in range(1, 8):
            with self.subTest(card=identifier):
                bought = self.activity(43, action="2", gifttype=str(identifier), paytype="1")
                self.assert_free(bought)
                card = bought["cards"][identifier - 1]
                for key in ("buytime", "paytype", "value", "price", "discount", "days", "giftList"):
                    self.assertIn(key, card)
                self.assertEqual(len(card["days"]), 31)
                self.assertEqual(card["days"][0], 2)
                self.assertEqual(card["endtime"], NOW + 31 * activities.DAY)
        self.assertEqual(server.PLAYER_STATE["rosemoney"], 1000)
        self.assert_saved()

    def test_monthly_claims_grant_actual_items_once_per_local_day(self):
        for identifier in range(1, 8):
            self.activity(43, action=2, gifttype=identifier)
            claim = self.activity(43, action=3, gifttype=identifier)
            self.assert_free(claim)
            self.assertEqual(claim["cards"][identifier - 1]["days"][0], 3)
        self.assertEqual(server.PLAYER_STATE["props"], {2: 1, 31005: 1, 120601006: 1, 31024: 1})
        self.assertEqual(server.PLAYER_STATE["seeds"][26071], 1)
        self.assertEqual(server.PLAYER_STATE["decorations"][132002022], 0)
        self.assertEqual(server.PLAYER_STATE["rosemoney"], 11000)
        before = copy.deepcopy(server.PLAYER_STATE)
        self.assertNotEqual(self.activity(43, action=3, gifttype=1)["result"], 0)
        self.assertEqual(server.PLAYER_STATE, before)
        # Purchases stack time but never reset a previously claimed daily gift.
        renewed = self.activity(43, action=2, gifttype=1)
        self.assertEqual(renewed["cards"][0]["endtime"], NOW + 62 * activities.DAY)
        self.assertNotEqual(self.activity(43, action=3, gifttype=1)["result"], 0)
        with patch("premium_activities.time.time", return_value=NOW + activities.DAY):
            self.assert_free(self.activity(43, action=3, gifttype=1))
        self.assertEqual(server.PLAYER_STATE["props"][2], 2)
        self.assert_saved()

    def test_monthly_renewal_after_expiry_starts_a_fresh_client_window(self):
        self.assert_free(self.activity(43, action=2, gifttype=1))
        after_expiry = NOW + 35 * activities.DAY
        with patch("premium_activities.time.time", return_value=after_expiry):
            bought = self.activity(43, action=2, gifttype=1)
            self.assertEqual(bought["cards"][0]["days"], [2] + [1] * 30)
            self.assertEqual(bought["cards"][0]["endtime"], after_expiry + 31 * activities.DAY)
            self.assert_free(self.activity(43, action=3, gifttype=1))
        self.assert_saved()

    def test_annual_purchase_status_and_real_october_rewards(self):
        initial = self.activity(12, action=1)
        self.assertEqual(len(initial["discount"]), 7)
        for identifier in range(1, 8):
            with self.subTest(card=identifier):
                bought = self.activity(12, action=2, gifttype=identifier)
                self.assert_free(bought)
                card = bought["gift%d" % identifier]
                self.assertEqual(card["gifttype"], identifier)
                self.assertEqual(card["bm"], 10)
                self.assertEqual(card["item"][0], {"m": 10, "s": 2})
                claimed = self.activity(12, action=3, gifttype=identifier)
                self.assert_free(claimed)
                self.assertEqual(claimed["gift%d" % identifier]["item"][0]["s"], 3)
                expected = server._catalog("GiftCardConfig.xml").find("card[@gifttype='%d']/month[@index='10']" % identifier)
                self.assertEqual([(award["type"], str(award["id"]), award["count"]) for award in claimed["award"]],
                                 [(int(item.get("type")), item.get("id"), int(item.get("count"))) for item in expected])
        self.assertEqual(server.PLAYER_STATE["seeds"][143], 1)
        self.assertEqual(server.PLAYER_STATE["props"][10], 2)
        self.assertEqual(server.PLAYER_STATE["props"][31004], 36000)
        self.assertEqual(server.PLAYER_STATE["rose_seeds"][24002], 3)
        self.assertGreater(server.PLAYER_STATE["activities"]["giftcard"]["baobao"]["300003355"], 0)
        self.assertNotIn(300003355, server.PLAYER_STATE["props"])
        self.assert_saved()

    def test_annual_month_change_and_charm_bonus(self):
        june = int(dt.datetime(2026, 6, 14, 12, tzinfo=activities.LOCAL_TIMEZONE).timestamp())
        with patch("premium_activities.time.time", return_value=june):
            self.assert_free(self.activity(12, action=2, gifttype=4))
            reward = self.activity(12, action=3, gifttype=4)
            self.assert_free(reward)
            self.assertEqual(server.PLAYER_STATE["activities"]["giftcard"]["charm_addon_end"], june + 120 * 60)
            before = copy.deepcopy(server.PLAYER_STATE)
            self.assertNotEqual(self.activity(12, action=3, gifttype=4)["result"], 0)
            self.assertEqual(server.PLAYER_STATE, before)
        july = int(dt.datetime(2026, 7, 1, tzinfo=activities.LOCAL_TIMEZONE).timestamp())
        with patch("premium_activities.time.time", return_value=july):
            self.assert_free(self.activity(12, action=3, gifttype=4))
        self.assertEqual(server.PLAYER_STATE["decorations"][120705005], 0)
        self.assertEqual(server.PLAYER_STATE["rose_seeds"][27], 3)
        self.assert_saved()

    def test_all_annual_configured_rewards_resolve_in_real_catalog(self):
        # Exercise every configured reward, including server ID aliases and pets.
        for card in server._catalog("GiftCardConfig.xml").findall("card"):
            identifier = int(card.get("gifttype"))
            for month in range(1, 13):
                timestamp = int(dt.datetime(2026, month, 14, 12, tzinfo=activities.LOCAL_TIMEZONE).timestamp())
                with self.subTest(card=identifier, month=month), patch("premium_activities.time.time", return_value=timestamp):
                    self.assert_free(self.activity(12, action=2, gifttype=identifier))
                    self.assert_free(self.activity(12, action=3, gifttype=identifier))
        self.assert_saved()

    def test_happy_egg_init_buy_draw_and_reward_preview(self):
        initial = self.activity(198, request=1)
        self.assert_free(initial)
        self.assertEqual(len(initial["subActivity"]), 2)
        self.assertEqual(initial["prop"], 0)
        bought = self.activity(198, request=2, count=5)
        self.assert_free(bought)
        self.assertEqual(bought["prop"], 5)
        preview = self.activity(198, request=4, index=2)
        self.assertGreater(len(preview["bigItem"]), 0)
        self.assertGreater(len(preview["item"]), 0)
        drawn = self.activity(198, request=3, index=2, count=10, auto=1)
        self.assert_free(drawn)
        self.assertEqual(drawn["prop"], 0)
        self.assertEqual(drawn["curLuck"], 0)
        self.assertEqual(drawn["specAward"], [{"type": 0, "id": 161391001, "count": 1}])
        for key in ("addLuck", "totlLuck", "curLuck", "left", "total", "cost1", "cost2", "cost3", "coolEndT", "now", "award"):
            self.assertIn(key, drawn)
        self.assertEqual(server.PLAYER_STATE["props"][2], 2)
        self.assertEqual(server.PLAYER_STATE["rose_seeds"][21], 2)
        self.assertEqual(server.PLAYER_STATE["props"][161391001], 1)
        self.assertEqual(server._inventory()["roseseed1"], 2)
        self.assert_saved()

    def test_petpk_discount_uses_icons_not_slot_ids(self):
        init = server.handle_cmd("rosary_talentpk_oper", {"type": 22, "request": 1})
        self.assertEqual([item["id"] for item in init["rushbuy"]], [37106, 37105, 37107])
        for index, identifier in enumerate((37106, 37105, 37107), 1):
            result = server.handle_cmd("rosary_talentpk_oper", {"type": 22, "request": 2, "index": index, "count": 2})
            self.assert_free(result)
            self.assertEqual(result["award"], {"type": 0, "id": identifier, "count": 2})
            self.assertEqual(server.PLAYER_STATE["props"][identifier], 2)
        self.assertTrue(all(index not in server.PLAYER_STATE["props"] for index in (1, 2, 3)))
        self.assert_saved()

    def test_petpk_shop_opens_real_rewards_and_currency_counts(self):
        for identifier in (60014, 1001, 1000, 141, 131, 60013):
            result = server.handle_cmd("rosary_talentpk_oper", {"type": 12, "id": identifier, "num": 2, "paytype": 1})
            self.assert_free(result)
            self.assertIsInstance(result["addprop"], list)
            self.assertTrue(result["addprop"])
            if identifier == 1000:
                self.assertEqual(result["addprop"][0]["type"], 5)
        self.assertEqual(server.PLAYER_STATE["rosemoney"], 21000)
        self.assertEqual(server.PLAYER_STATE["charm"], 200)
        self.assertEqual(server.PLAYER_STATE["seeds"], {141: 2, 131: 2})
        self.assertEqual(server.PLAYER_STATE["props"], {30022: 2, 37000: 2})
        self.assert_saved()

    def test_petpk_augury_and_gift_persist_real_prizes(self):
        for kind in (1, 2):
            result = server.handle_cmd("rosary_talentpk_oper", {"type": 24, "augury": kind, "paytype": 1})
            self.assert_free(result)
            self.assertTrue(result["prize"])
            self.assertEqual(set(result["augury"]), {"free1", "free2", "pay1", "pay2"})
            self.assertTrue(all(len(row) == 3 for row in result["augury"].values()))
        gift = server.handle_cmd("rosary_talentpk_oper", {"type": 26, "paytype": 1})
        self.assert_free(gift)
        self.assertEqual([award["id"] for award in gift["prize"]], [37105, 37106, 37107])
        self.assertEqual(server.PLAYER_STATE["props"], {37105: 2, 37106: 2, 37107: 1})
        self.assert_saved()

    def test_dingxiang_energy_and_subscription(self):
        initial = self.activity(1001)
        self.assert_free(initial)
        self.assertEqual(initial["energy"], 0)
        # The shipped client reads all five slots before processing later requests.
        self.assertEqual(len(initial["skills"]), 5)
        for skill in initial["skills"]:
            self.assertIsInstance(skill["need_flower"], list)
            self.assertIsInstance(skill["need_rose"], list)
        bought = self.activity(1010, is_pay=1, count=2)
        self.assert_free(bought)
        self.assertEqual((bought["energy"], bought["count"]), (100, 2))
        first = self.activity(1012, pay_month=1)
        second = self.activity(1012, pay_month=2)
        self.assert_free(second)
        self.assertEqual((first["effect_day"], second["effect_day"]), (30, 90))
        self.assertEqual(second["award"], [])
        server.PLAYER_STATE["props"][120601006] = 3
        used = self.activity(1010, is_pay=0, count=2)
        self.assertEqual(used["energy"], 200)
        self.assertEqual(server.PLAYER_STATE["props"][120601006], 1)
        self.assert_saved()

    def test_smelt_stone_returns_cumulative_count(self):
        first = self.activity(192, request=1, count=3)
        second = self.activity(192, request=1, count=2)
        self.assert_free(second)
        self.assertEqual((first["count"], second["count"]), (3, 5))
        self.assertEqual(second["now"], NOW)
        self.assertEqual(server.PLAYER_STATE["props"][161209006], 5)
        self.assert_saved()

    def test_material_machine_uses_actual_wheel_and_free_steps(self):
        first = server.handle_cmd("rosary0903_begin_play", {"kind": 1, "type": 1, "play_free": 0})
        self.assert_free(first)
        self.assertEqual((first["currentaward"], first["currentawardtype"]), (1, 18))
        self.assertEqual((first["totalstep"], first["currentstep"]), (3, 1))
        for identifier in (2, 3):
            result = server.handle_cmd("rosary0903_play", {})
            self.assert_free(result)
            self.assertEqual(result["currentaward"], identifier)
            self.assertEqual(result["svrData"], {"materialAward": None, "nationalAward": [], "gatherprop": []})
        self.assertEqual(server.PLAYER_STATE["rose_seeds"], {21: 1, 22: 1, 23: 1})
        self.assertNotIn(1, server.PLAYER_STATE["props"])
        self.assert_saved()
        before = copy.deepcopy(server.PLAYER_STATE)
        self.assertNotEqual(server.handle_cmd("rosary0903_play", {})["result"], 0)
        self.assertEqual(server.PLAYER_STATE, before)

    def test_material_wheel_items_are_real_and_grantable(self):
        for wheel in (1, 2, 3, 4, 5):
            config = server._catalog("rollPlateConfig.xml").find("rollInfo/plate[@type='%d']" % wheel)
            allowed = {(int(item.get("id")), int(item.get("type"))) for item in config}
            for _ in range(len(config)):
                with self.subTest(wheel=wheel):
                    result = server.handle_cmd("rosary0903_begin_play", {"kind": 1, "type": wheel, "play_free": 0})
                    self.assert_free(result)
                    self.assertIn((result["currentaward"], result["currentawardtype"]), allowed)
                    # getPropCfg resolves seed ID 1 before the fertilizer with
                    # local ID 1. The old duplicate free-wheel entry is skipped.
                    self.assertNotEqual(result["currentawardname"], "普通化肥")
        self.assert_saved()

    def test_concurrent_draws_and_purchases_keep_all_grants(self):
        def buy(_):
            return self.activity(198, request=2, count=3)
        with ThreadPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(buy, range(8)))
        self.assertTrue(all(result["result"] == 0 for result in replies))
        self.assertEqual(server.PLAYER_STATE["activities"]["happy_egg"]["hammers"], 24)
        with ThreadPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(lambda _: self.activity(198, request=3, index=2, count=5), range(8)))
        self.assertTrue(all(result["result"] == 0 for result in replies))
        self.assertEqual(server.PLAYER_STATE["props"][2], 8)
        self.assertEqual(server.PLAYER_STATE["props"][161391001], 4)
        self.assertEqual(server.PLAYER_STATE["activities"]["happy_egg"]["hammers"], 0)
        self.assert_saved()

    def test_storage_failure_rolls_back_entitlements_and_rewards(self):
        for command, params in [
            ("rosary_activity_oper", {"cmd": 43, "action": 2, "gifttype": 1}),
            ("rosary_activity_oper", {"cmd": 198, "request": 3, "index": 2, "count": 5}),
            ("rosary_talentpk_oper", {"type": 22, "request": 2, "index": 1, "count": 2}),
            ("rosary_activity_oper", {"cmd": 1012, "pay_month": 1}),
        ]:
            before = copy.deepcopy(server.PLAYER_STATE)
            with self.subTest(command=command, params=params), patch.object(server, "_save_player_state", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    server.handle_cmd(command, params)
            self.assertEqual(server.PLAYER_STATE, before)

    def test_invalid_orders_leave_state_unchanged(self):
        invalid = [
            ("rosary_activity_oper", {"cmd": 43, "action": 2, "gifttype": 8}),
            ("rosary_activity_oper", {"cmd": 12, "action": 3, "gifttype": 1}),
            ("rosary_activity_oper", {"cmd": 198, "request": 2, "count": 0}),
            ("rosary_activity_oper", {"cmd": 198, "request": 3, "index": "NaN"}),
            ("rosary_talentpk_oper", {"type": 12, "id": 1, "num": 1}),
            ("rosary_talentpk_oper", {"type": 22, "request": 2, "index": 4, "count": 1}),
            ("rosary_talentpk_oper", {"type": 24, "augury": 3}),
            ("rosary_activity_oper", {"cmd": 1010, "count": -1}),
            ("rosary_activity_oper", {"cmd": 1010, "count": 1, "is_pay": 0}),
            ("rosary_activity_oper", {"cmd": 1012, "pay_month": 0}),
            ("rosary_activity_oper", {"cmd": 192, "request": 1, "count": "Infinity"}),
            ("rosary0903_begin_play", {"kind": 2, "type": 1}),
        ]
        before = copy.deepcopy(server.PLAYER_STATE)
        for command, params in invalid:
            with self.subTest(command=command, params=params):
                self.assertNotEqual(server.handle_cmd(command, params)["result"], 0)
                self.assertEqual(server.PLAYER_STATE, before)


if __name__ == "__main__":
    unittest.main()
