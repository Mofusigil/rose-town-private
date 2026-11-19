import copy
import http.server
import json
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import private_server as server


class LocalPaymentTests(unittest.TestCase):
    def setUp(self):
        self.original = copy.deepcopy(server.PLAYER_STATE)
        self.original_file = server.STATE_FILE
        self.directory = tempfile.TemporaryDirectory()
        server.STATE_FILE = str(pathlib.Path(self.directory.name) / "player.json")
        server.PLAYER_STATE.clear()
        server.PLAYER_STATE.update(server._load_player_state())

    def tearDown(self):
        server.PLAYER_STATE.clear()
        server.PLAYER_STATE.update(self.original)
        server.STATE_FILE = self.original_file
        self.directory.cleanup()

    def test_all_configured_point_seeds_work_with_zero_balance(self):
        purchased = 0
        for identifier, seed in server._seeds().items():
            if int(seed.get("seedPriceQPoint") or 0) <= 0:
                continue
            with self.subTest(seed=identifier):
                response = server.handle_cmd("rosary_qb_buy_seed", {
                    "seedtype": str(identifier), "count": "1", "paytype": "1"})
                self.assertEqual(response["result"], 0)
                self.assertEqual(response["balance"], 0)
                self.assertEqual(server.PLAYER_STATE["seeds"][identifier], 1)
                purchased += 1
        self.assertGreater(purchased, 0)
        self.assertEqual(server._load_player_state(), server.PLAYER_STATE)

    def test_props_bundles_and_inventory_survive_reload(self):
        operations = [
            ("rosary_buy_game_props", {"buyid": "161391001", "count": "3"}),
            ("rosary0906_buy_fertilizer", {"buytype": "1", "buycount": "2"}),
            ("rosary0906_buy_fertilizer", {"buytype": "9", "buycount": "2"}),
            ("rosary0906_buy_fertilizer", {"buytype": "8", "buycount": "1"}),
            ("rosary0906_buy_fertilizer", {"buytype": "111", "buycount": "1"}),
            ("rosary0903_sale", {"buytype": "10", "buycount": "3"}),
        ]
        for cmd, params in operations:
            response = server.handle_cmd(cmd, {**params, "paytype": "1"})
            self.assertEqual(response["result"], 0, response)
            self.assertEqual(response["balance"], 0)
        self.assertEqual(server.PLAYER_STATE["props"], {
            161391001: 3, 1: 2, 10: 7, 2: 2, 3: 2, 13: 2, 7: 11, 4: 12})
        self.assertEqual(server._load_player_state(), server.PLAYER_STATE)
        response = server.handle_cmd("rosary0907_get_init_second", {})
        self.assertEqual(response["commonferti"], 2)
        self.assertEqual(response["rose13"], [2, 0])
        self.assertEqual(response["prop161391001"], 3)

    def test_large_ids_rose_seeds_and_charm_flowers(self):
        self.assertEqual(server.handle_cmd("rosary0903_sale", {
            "buytype": "21", "buycount": "4", "paytype": "1"})["result"], 0)
        response = server.handle_cmd("rosary_activity_oper", {
            "cmd": "236", "request": "2", "id": "161281008", "count": "2"})
        self.assertEqual(response["result"], 0)
        self.assertEqual(server.PLAYER_STATE["props"][161281008], 2)
        self.assertEqual(server._inventory()["roseseed1"], 4)

    def test_fairy_chest_grants_a_configured_item(self):
        response = server.handle_cmd("rosary_buy_game_props", {
            "buyid": "60006", "count": "2", "paytype": "1"})
        self.assertEqual((response["result"], response["id"], response["num"]), (0, 31020, 2))
        self.assertEqual(server.PLAYER_STATE["props"][31020], 2)
        self.assertEqual(response["balance"], 0)

    def test_decorations_buy_renew_equip_and_reload(self):
        params = {"buytype": "49", "paytype": "1"}
        first = server.handle_cmd("rosary0906_buy_decorate", params)
        second = server.handle_cmd("rosary0906_buy_decorate", {**params, "action": "1"})
        self.assertEqual((first["result"], first["effecttime"]), (0, 60))
        self.assertEqual(second["effecttime"], 120)
        self.assertEqual(second["paycount"], 0)
        used = server.handle_cmd("rosary0906_use_decorate", {"usetype": "49", "dotype": "1"})
        self.assertEqual(used["result"], 0)
        self.assertEqual(server._plantation_payload()["soil1"][0]["decorpot"], 49)
        initial = server.handle_cmd("rosary0907_get_init_second", {})
        self.assertEqual(initial["fpot"][0]["pot49"][0]["eday"], 120)
        self.assertEqual(server._load_player_state(), server.PLAYER_STATE)

    def test_vip_and_sunshine_extend_without_spending(self):
        vip_params = {"cmd": "211", "request": "2", "index": "12"}
        first = server.handle_cmd("rosary_activity_oper", vip_params)
        second = server.handle_cmd("rosary_activity_oper", {**vip_params, "index": "1"})
        self.assertEqual(first["result"], 0)
        self.assertEqual(second["roseLifeVIP"]["timeEnd"] - first["roseLifeVIP"]["timeEnd"], 30 * 86400)
        self.assertGreater(second["roseLifeVIP"]["level"], 0)
        self.assertEqual(second["balance"], 0)
        sun_params = {"cmd": "55", "request": "2", "index": "2", "paytype": "1"}
        first = server.handle_cmd("rosary_activity_oper", sun_params)
        second = server.handle_cmd("rosary_activity_oper", sun_params)
        self.assertEqual((first["value"], second["value"]), (300, 300))
        self.assertEqual(second["time"] - first["time"], 90 * 86400)
        self.assertEqual(server._load_player_state(), server.PLAYER_STATE)

    def test_pet_renewal_and_paid_pots(self):
        params = {"pt": "4", "petseq": "1", "month": "1", "auto_renewal": "1"}
        first = server.handle_cmd("rosary_pets_feed", params)
        second = server.handle_cmd("rosary_pets_feed", params)
        self.assertEqual((first["effectday"], second["effectday"]), (30, 60))
        self.assertEqual(second["pay_count"], 0)
        self.assertEqual(second["award_type"], 0)
        response = server.handle_cmd("rosary0904_expand", {"action": "1", "soilno": "1", "paytype": "1"})
        self.assertEqual(response["potlevel"], 1)
        response = server.handle_cmd("rosary0904_expand", {
            "soilno": "9", "action": "6", "actionop": "1", "paytype": "1"})
        self.assertEqual(response["SoilType"], 2)
        self.assertEqual(server._plantation_payload()["soilcount"], 9)
        self.assertEqual(server._load_player_state(), server.PLAYER_STATE)

    def test_vip_gifts_grant_configured_contents_once(self):
        server.handle_cmd("rosary_activity_oper", {"cmd": "211", "request": "2", "index": "12"})
        params = {"cmd": "211", "request": "3", "index": "1"}
        first = server.handle_cmd("rosary_activity_oper", params)
        second = server.handle_cmd("rosary_activity_oper", params)
        self.assertEqual([item["id"] for item in first["award"]], [120705046, 120705047, 22022])
        self.assertEqual(second["award"], [])
        self.assertIn(120705046, server.PLAYER_STATE["decorations"])
        self.assertEqual(server._inventory()["roseseed22022"], 2)
        first_daily = server.handle_cmd("rosary0912_gamevip_gifts", {})
        second_daily = server.handle_cmd("rosary0912_gamevip_gifts", {})
        self.assertEqual(first_daily["gift"][0]["addprop506"], 2)
        self.assertEqual(second_daily["gift"], [{}])
        initial = server.handle_cmd("rosary0909_get_init_first_self", {})
        self.assertEqual(initial["roseLifeVIP"]["gift"], 1)
        self.assertEqual(initial["roseLifeVIP"]["vipGift"], 1)
        self.assertEqual(server._load_player_state(), server.PLAYER_STATE)

    def test_concurrent_free_orders_and_save_failure(self):
        params = {"buyid": "161391003", "count": "2", "paytype": "1"}
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _: server.handle_cmd("rosary_buy_game_props", params), range(8)))
        self.assertTrue(all(response["result"] == 0 for response in results))
        self.assertEqual(server.PLAYER_STATE["props"][161391003], 16)
        before = copy.deepcopy(server.PLAYER_STATE)
        with patch.object(server, "_save_player_state", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                server.handle_cmd("rosary_buy_game_props", params)
        self.assertEqual(server.PLAYER_STATE, before)

    def test_unsupported_activity_rejects_purchase_without_retaining_credentials(self):
        previous = copy.deepcopy(server.PLAYER_STATE)
        response = server.handle_cmd("rosary_activity_oper", {
            "cmd": "987654", "request": "2", "count": "3", "__local_paid": "1",
            "__local_action": "BuyTickets", "openid": "secret-openid", "token": "secret-token"})
        self.assertNotEqual(response["result"], 0)
        self.assertTrue(response["local_unsupported"])
        self.assertEqual(server.PLAYER_STATE, previous)
        self.assertNotIn("local_receipt", response)
        self.assertNotIn("secret", json.dumps(server.PLAYER_STATE))

    def test_http_local_recharge_get_parameters_and_gray_suffix(self):
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        origin = "http://127.0.0.1:%d" % httpd.server_port
        try:
            request = urllib.request.Request(origin + "/local_payments", method="POST",
                data=json.dumps({"action": "recharge", "count": 200}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request) as reply:
                self.assertEqual(json.load(reply)["balance"], 200)
            with urllib.request.urlopen(origin + "/cgi-bin/rosary_qb_buy_seed_go?seedtype=26147&count=2") as reply:
                result = json.load(reply)
                self.assertEqual((result["result"], result["count"], result["balance"]), (0, 2, 200))
            with urllib.request.urlopen(origin + "/assets/main/index.57d00.js") as reply:
                code = reply.read().decode()
                self.assertIn(origin + "/cgi-bin/", code)
                self.assertEqual(reply.headers["Cache-Control"], "no-store")
            self.assertEqual(server._load_player_state(), server.PLAYER_STATE)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()

    def test_invalid_orders_leave_state_unchanged(self):
        before = copy.deepcopy(server.PLAYER_STATE)
        for cmd, params in [
            ("rosary_buy_game_props", {"buyid": "999999999", "count": "1"}),
            ("rosary_buy_game_props", {"buyid": "161391001", "count": "0"}),
            ("rosary0906_buy_decorate", {"buytype": "NaN"}),
            ("rosary0906_buy_decorate", {"buytype": "49", "paytype": "bad"}),
            ("rosary_pets_feed", {"pt": "4", "petseq": "1", "month": "-1"}),
            ("rosary_pets_feed", {"pt": "4", "petseq": "1", "auto_renewal": "bad"}),
            ("rosary_pets_feed", {"pt": "4", "petseq": "1", "auto_renewal": "2"}),
            ("rosary_activity_oper", {"cmd": "211", "request": "2", "index": "0"}),
        ]:
            with self.subTest(cmd=cmd, params=params):
                self.assertNotEqual(server.handle_cmd(cmd, params)["result"], 0)
                self.assertEqual(server.PLAYER_STATE, before)

    def test_expired_decoration_cannot_be_equipped_or_rendered(self):
        with patch.object(server.time, "time", return_value=2000000000):
            server.handle_cmd("rosary0906_buy_decorate", {"buytype": "49"})
            server.handle_cmd("rosary0906_use_decorate", {"usetype": "49"})
        with patch.object(server.time, "time", return_value=2000000000 + 60 * 86400):
            before = copy.deepcopy(server.PLAYER_STATE)
            response = server.handle_cmd("rosary0906_use_decorate", {"usetype": "49"})
            self.assertNotEqual(response["result"], 0)
            self.assertEqual(server.PLAYER_STATE, before)
            self.assertEqual(server._plantation_payload()["soil1"][0]["decorpot"], 0)
            inventory = server._decoration_inventory()
            self.assertEqual(inventory["decorate49"][0]["isuse"], 0)
            self.assertEqual(inventory["pot49"], [0, 0])
            self.assertNotEqual(inventory["fpot"][0].get("pot0"), 49)
            server.handle_cmd("rosary0906_buy_decorate", {"buytype": "49"})
            self.assertEqual(server._plantation_payload()["soil1"][0]["decorpot"], 49)

    def test_permanent_decoration_is_not_downgraded_by_renewal_or_rewards(self):
        server.PLAYER_STATE["decorations"][49] = 0
        server.handle_cmd("rosary0906_buy_decorate", {"buytype": "49"})
        self.assertEqual(server.PLAYER_STATE["decorations"][49], 0)
        server._grant_awards([{"type": 10, "id": 49, "count": 1}])
        self.assertEqual(server.PLAYER_STATE["decorations"][49], 0)

    def test_failed_atomic_replace_preserves_disk_and_memory_and_cleans_temporary_file(self):
        server._save_player_state()
        before = copy.deepcopy(server.PLAYER_STATE)
        saved = pathlib.Path(server.STATE_FILE).read_bytes()
        with patch.object(server.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                server.local_payment({"action": "recharge", "count": 20})
        self.assertEqual(server.PLAYER_STATE, before)
        self.assertEqual(pathlib.Path(server.STATE_FILE).read_bytes(), saved)
        self.assertEqual(list(pathlib.Path(self.directory.name).glob("*.tmp")), [])

    def test_recharge_rejects_non_integer_json_quantities(self):
        before = copy.deepcopy(server.PLAYER_STATE)
        for count in (1.5, True, float("inf"), float("nan"), None):
            with self.subTest(count=count):
                response = server.local_payment({"action": "recharge", "count": count})
                self.assertNotEqual(response["result"], 0)
                self.assertEqual(server.PLAYER_STATE, before)

    def test_pet_days_are_recalculated_after_time_passes_and_reload(self):
        with patch.object(server.time, "time", return_value=2000000000):
            server.handle_cmd("rosary_pets_feed", {"pt": "4", "petseq": "1", "month": "1"})
        server.PLAYER_STATE.update(server._load_player_state())
        for days, expected in ((3, 27), (30, 0), (40, 0)):
            with patch.object(server.time, "time", return_value=2000000000 + days * 86400):
                pets = server.handle_cmd("rosary0903_get_takeon_pets", {})["pets"]
                self.assertEqual(pets[0]["efday"], expected)


if __name__ == "__main__":
    unittest.main()
