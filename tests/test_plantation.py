import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import private_server as server
import test_shop


class PlantationTests(unittest.TestCase):
    setUp = test_shop.ShopGatewayTests.setUp
    tearDown = test_shop.ShopGatewayTests.tearDown

    def test_wire_time_uses_china_timezone_independently_of_host(self):
        self.assertEqual(server._server_date(0), "1970-01-01-08-00-00")

    def plant(self, pot=1, flower=28078):
        return server.handle_cmd("rosary0904_soil_plant_rose", {
            "soilno": str(pot), "rosetype": str(flower)})

    def test_initial_free_pots_have_valid_client_fields(self):
        response = server.handle_cmd("rosary0908_get_plant_info_self", {})
        self.assertEqual(response["soilcount"], 8)
        types = [response["soil%d" % n][0]["SoilType"] for n in range(1, 9)]
        self.assertEqual(types, [0] * 6 + [1] * 2)
        for n in range(1, 9):
            pot = response["soil%d" % n][0]
            self.assertEqual(pot["soilno"], n)
            self.assertEqual(pot["soilsate"], 51)
            self.assertEqual(pot["rosestate"], 0)
            self.assertNotIn("stealflag", pot)

    def test_old_shop_save_migrates_without_losing_seeds(self):
        with open(server.STATE_FILE, "w") as saved:
            json.dump({"rosemoney": 334, "balance": 0, "seeds": {"26078": 1}}, saved)
        loaded = server._load_player_state()
        self.assertEqual(loaded["rosemoney"], 334)
        self.assertEqual(loaded["seeds"][26078], 1)
        self.assertEqual(len(loaded["pots"]), 8)

    def test_plant_root_response_and_refresh_persist(self):
        server.PLAYER_STATE["seeds"][26078] = 1
        response = self.plant()
        self.assertEqual(response["result"], 0)
        self.assertEqual(response["soilno"], 1)
        self.assertEqual(response["soilsate"], 28078)
        self.assertEqual(response["vegetableseed26078"], 0)
        self.assertEqual(response["rosestate"], 1)
        self.assertRegex(response["rosebegintime"], r"^\d{4}(?:-\d{2}){5}$")
        self.assertEqual(server._load_player_state(), server.PLAYER_STATE)
        initial = server.handle_cmd("rosary0908_get_plant_info_self", {})
        self.assertEqual(initial["soil1"][0]["soilsate"], 28078)

    def test_invalid_pots_types_and_occupied_pots_preserve_inventory(self):
        server.PLAYER_STATE["seeds"][26078] = 1
        before = copy.deepcopy(server.PLAYER_STATE)
        for pot, flower in [(0, 28078), (99, 28078), (7, 28078), (1, 999999)]:
            self.assertNotEqual(self.plant(pot, flower)["result"], 0)
            self.assertEqual(server.PLAYER_STATE, before)
        self.assertEqual(self.plant()["result"], 0)
        before = copy.deepcopy(server.PLAYER_STATE)
        self.assertNotEqual(self.plant()["result"], 0)
        self.assertEqual(server.PLAYER_STATE, before)

    def test_water_flower_requires_water_pot(self):
        server.PLAYER_STATE["seeds"][26144] = 1
        self.assertNotEqual(self.plant(1, 28144)["result"], 0)
        self.assertEqual(self.plant(7, 28144)["result"], 0)

    def test_concurrent_planting_consumes_single_seed(self):
        server.PLAYER_STATE["seeds"][26078] = 1
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(self.plant, [1, 2]))
        self.assertEqual(sum(response["result"] == 0 for response in results), 1)
        self.assertEqual(server.PLAYER_STATE["seeds"][26078], 0)

    def test_growth_harvest_and_clear_cycle(self):
        server.PLAYER_STATE["seeds"][26078] = 1
        self.assertEqual(self.plant()["result"], 0)
        self.assertNotEqual(server.handle_cmd("rosary0904_gain", {"soilno": "1"})["result"], 0)
        started = server.PLAYER_STATE["pots"][1]["planted_at"]
        with patch.object(server.time, "time", return_value=started + 900 * 60):
            initial = server.handle_cmd("rosary0908_get_plant_info_self", {})
            self.assertEqual(initial["soil1"][0]["rosestate"], 5)
            response = server.handle_cmd("rosary0904_gain", {"soilno": "1", "rosetype": "6"})
        self.assertEqual(response["result"], 0)
        self.assertEqual(response["soilsate"], 50)
        self.assertEqual(response["igainrosetype"], 28078)
        self.assertEqual(response["vegetablefruit28078"], 31)
        self.assertEqual(response["addexperice"], 173)
        self.assertEqual(response["addcharm"], 18)
        self.assertNotEqual(server.handle_cmd("rosary0904_gain", {"soilno": "1"})["result"], 0)
        cleared = server.handle_cmd("rosary0904_hoe", {"soilno": "1", "rosetype": "2"})
        self.assertEqual(cleared["soilsate"], 51)
        self.assertEqual(cleared["rosebegintime"], "")
        self.assertEqual(server.PLAYER_STATE["seeds"][26078], 0)


if __name__ == "__main__":
    unittest.main()
