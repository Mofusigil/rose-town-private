import copy
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

import gameplay
import private_server as server
import test_shop


NOW = 1791950400


class GameplayTests(unittest.TestCase):
    setUp = test_shop.ShopGatewayTests.setUp
    tearDown = test_shop.ShopGatewayTests.tearDown

    def call(self, command, **params):
        with patch.object(server.time, "time", return_value=NOW):
            return server.handle_cmd(command, params)

    def smelt(self, **params):
        order = {"cmd": 192, "request": 2, "potID": 120705048,
                 "attrType": 1, "auto": 0, "soilno": 0,
                 "count": 1, "id1": 161209001, "count1": 10}
        order.update(params)
        return self.call("rosary_activity_oper", **order)

    def prepare_smelt(self):
        server.PLAYER_STATE["decorations"][120705048] = 0
        server.PLAYER_STATE["props"][161209001] = 20
        server.PLAYER_STATE["props"][161209005] = 2
        server.PLAYER_STATE["rosemoney"] = 100000000

    def assert_saved(self):
        self.assertEqual(server._load_player_state(), server.PLAYER_STATE)

    def assert_rejected_without_changes(self, action):
        before = copy.deepcopy(server.PLAYER_STATE)
        server._save_player_state()
        disk = Path(server.STATE_FILE).read_bytes()
        response = action()
        self.assertNotEqual(response["result"], 0, response)
        self.assertEqual(server.PLAYER_STATE, before)
        self.assertEqual(Path(server.STATE_FILE).read_bytes(), disk)

    def test_named_pet_fields_match_client_and_expiry_reads_do_not_write(self):
        self.call("rosary_pets_feed", pt=4, petseq=1, month=1)
        response = self.call("rosary0903_get_takeon_pets")
        self.assertEqual(response["TPetInfo3"]["seq"], 1)
        self.assertEqual(response["TPetInfo3"]["efday"], 30)
        self.assertRegex(response["TPetInfo3"]["birthday"], r"^\d{4}-\d{2}-\d{2}$")
        before = copy.deepcopy(server.PLAYER_STATE)
        with patch.object(server.time, "time", return_value=NOW + 31 * gameplay.DAY):
            expired = server.handle_cmd("rosary0903_get_takeon_pets", {})
        self.assertEqual(expired["TPetInfo3"]["efday"], 0)
        self.assertEqual(server.PLAYER_STATE, before)
        self.assert_saved()

    def test_giftcard_baby_award_becomes_a_real_named_instance(self):
        self.call("rosary_activity_oper", cmd=12, action=2, gifttype=1)
        response = self.call("rosary_activity_oper", cmd=12, action=3, gifttype=1)
        self.assertEqual(response["result"], 0, response)
        pet = self.call("rosary0903_get_takeon_pets")["TakeonPetInfo"]
        self.assertEqual(pet["avatarid"], 300003355)
        self.assertEqual((pet["lv"], pet["dex"], pet["efday"], pet["show"]), (1, 1, 30, 1))
        self.assert_saved()

    def test_baby_care_persists_nickname_visibility_and_all_food_effects(self):
        gameplay.grant_baby(server.PLAYER_STATE, 300003355, 1, NOW)
        pet = server.PLAYER_STATE["pets"][1]
        server.PLAYER_STATE["props"].update({4: 3, 320: 3, 321: 3})
        nick = self.call("rosary_set_pet_neck", petseq=1, nick="  花园宝宝  ")
        self.assertEqual(nick["strPetNick"], "花园宝宝")
        self.assertEqual(self.call("rosary_set_pet_status", pt=0, st=0)["st"], 0)
        effects = ((115, "phadd", 200), (320, "evadd", 2), (321, "lfadd", 2))
        for identifier, key, expected in effects:
            response = self.call("rosary_talent_pet_feed", pt=0, mi=identifier, count=2)
            self.assertEqual(response["result"], 0, response)
            self.assertEqual(response[key], expected)
            self.assertEqual(response["nm"], 1)
        self.assertEqual((pet["ph"], pet["evo"], pet["efday"]), (300, 2, 32))
        pet = self.call("rosary0903_get_takeon_pets")["TakeonPetInfo"]
        self.assertEqual((pet["nick"], pet["show"]), ("花园宝宝", 0))
        self.assert_saved()

    def test_bad_care_orders_and_type_mismatch_preserve_state(self):
        gameplay.grant_baby(server.PLAYER_STATE, 300003355, 1, NOW)
        for cmd, params in [
            ("rosary_set_pet_neck", {"petseq": 1, "nick": "\n"}),
            ("rosary_set_pet_status", {"pt": 0, "st": 2}),
            ("rosary_set_pet_status", {"pt": 6, "st": 1}),
            ("rosary_talent_pet_feed", {"pt": 0, "mi": 320, "count": 1}),
            ("rosary_talent_pet_feed", {"pt": 0, "mi": 320, "count": True}),
            ("rosary_pets_feed", {"pt": 4, "petseq": 1, "month": 1}),
            ("rosary_pets_feed", {"pt": 0, "petseq": 2, "month": 1}),
        ]:
            with self.subTest(cmd=cmd, params=params):
                self.assert_rejected_without_changes(lambda: self.call(cmd, **params))

    def test_ordinary_baby_can_be_renewed_after_expiry(self):
        gameplay.grant_baby(server.PLAYER_STATE, 300003355, 1, NOW - 40 * gameplay.DAY)
        response = self.call("rosary_pets_feed", pt=0, petseq=1, month=1)
        self.assertEqual((response["result"], response["effectday"]), (0, 30))
        self.assert_saved()

    def test_hiding_a_reawarded_baby_does_not_switch_the_carried_instance(self):
        for identifier in (300003355, 300003288, 300003355):
            gameplay.grant_baby(server.PLAYER_STATE, identifier, 1, NOW)
        self.assertEqual(self.call("rosary0903_get_takeon_pets")["TakeonPetInfo"]["avatarid"], 300003355)
        self.assertEqual(self.call("rosary_set_pet_status", pt=0, st=0)["result"], 0)
        pet = self.call("rosary0903_get_takeon_pets")["TakeonPetInfo"]
        self.assertEqual((pet["avatarid"], pet["show"]), (300003355, 0))
        self.assert_saved()

    def test_legacy_baby_counter_migrates_once_without_sliding_expiry(self):
        server.PLAYER_STATE["activities"]["giftcard"] = {"baobao": {"300003355": 1}}
        server._save_player_state()
        os.utime(server.STATE_FILE, (NOW, NOW))
        first = server._load_player_state()
        second = server._load_player_state()
        self.assertEqual(first, second)
        self.assertEqual(first["pets"][1]["expires_at"], NOW + 30 * gameplay.DAY)
        server.PLAYER_STATE.clear()
        server.PLAYER_STATE.update(first)
        server._save_player_state()
        self.assert_saved()
        self.assertEqual(len(server._load_player_state()["pets"]), 1)

    def test_smelt_consumes_materials_gold_and_restores_upgrade_on_init(self):
        self.prepare_smelt()
        response = self.smelt()
        self.assertEqual(response["result"], 0, response)
        self.assertEqual(response["potInfo"]["speed"], [1, 100, 100, 200])
        self.assertEqual(server.PLAYER_STATE["props"][161209001], 10)
        self.assertEqual(response["coin"], 100000000 - 320000)
        initial = self.call("rosary0907_get_init_second")
        self.assertEqual(next(p for p in initial["dragonPotList"] if p["id"] == 120705048), response["potInfo"])
        self.assertEqual(len(initial["dragonPotList"]), len(gameplay.DRAGON_POT_IDS))
        self.assertEqual(initial["local_smelt_rule"], gameplay.LOCAL_SMELT_RULE)
        self.assertEqual(initial["usePersonalTheme"], 0)
        self.assert_saved()

    def test_smelt_rejects_insufficient_duplicate_or_invalid_materials_atomically(self):
        self.prepare_smelt()
        for params in ({"count1": 21}, {"potID": 999}, {"id1": 999},
                       {"count": 2, "id2": 161209001, "count2": 1},
                       {"count1": 1.5}, {"auto": True}, {"attrType": 0}):
            with self.subTest(params=params):
                self.assert_rejected_without_changes(lambda: self.smelt(**params))
        server.PLAYER_STATE["rosemoney"] = 0
        self.assert_rejected_without_changes(self.smelt)

    def test_smelt_stones_cover_crossed_levels_and_auto_purchase_deficit(self):
        self.prepare_smelt()
        server.PLAYER_STATE["activities"]["smelt_pots"] = {"120705048": {"speed": 750}}
        server.PLAYER_STATE["props"][gameplay.STONE_ID] = 20
        self.assert_rejected_without_changes(lambda: self.smelt(id1=161209005, count1=1))
        response = self.smelt(id1=161209005, count1=1, auto=1)
        self.assertEqual(response["result"], 0, response)
        self.assertEqual(response["local_auto_bought_stones"], 130)
        self.assertEqual(response["potInfo"]["speed"], [9, 950, 900, 1000])
        self.assertEqual(response["prop"], 0)
        self.assertEqual(response["balance"], 50)
        self.assert_saved()

    def test_smelt_cap_does_not_spend_stones_for_excess_experience(self):
        self.prepare_smelt()
        server.PLAYER_STATE["activities"]["smelt_pots"] = {"120705048": {"speed": 950}}
        server.PLAYER_STATE["props"][gameplay.STONE_ID] = 60
        response = self.smelt(id1=161209005, count1=1)
        self.assertEqual(response["potInfo"]["speed"], [10, 1000, 1000, 0])
        self.assertEqual(response["prop"], 10)
        self.assert_rejected_without_changes(self.smelt)

    def test_equipped_material_cannot_be_smelted(self):
        self.prepare_smelt()
        server.PLAYER_STATE["decorations"][120705032] = 0
        server.PLAYER_STATE["active_decorations"]["pot0"] = 120705032
        self.assert_rejected_without_changes(lambda: self.smelt(id1=120705032, count1=1))

    def test_equipped_pot_slots_use_the_client_scalar_fpot_shape(self):
        self.prepare_smelt()
        response = self.call("rosary0906_use_decorate", usetype=120705048)
        self.assertEqual(response["result"], 0, response)
        self.assertEqual(response["fpot"], [{"soil": 120705048}])
        self.assertEqual(response["pot120705048"], [1, 1])
        self.assert_saved()

    def test_concurrent_smelt_orders_cannot_double_spend_last_material(self):
        self.prepare_smelt()
        server.PLAYER_STATE["props"][161209001] = 10
        order = {"cmd": 192, "request": 2, "potID": 120705048,
                 "attrType": 1, "count": 1, "id1": 161209001, "count1": 10}
        with patch.object(server.time, "time", return_value=NOW), ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: server.handle_cmd("rosary_activity_oper", order), range(2)))
        self.assertEqual(sum(result["result"] == 0 for result in responses), 1)
        self.assertEqual(server.PLAYER_STATE["props"][161209001], 0)
        self.assert_saved()

    def test_real_save_replace_failure_rolls_back_smelt_and_care(self):
        self.prepare_smelt()
        gameplay.grant_baby(server.PLAYER_STATE, 300003355, 1, NOW)
        for action in (self.smelt, lambda: self.call("rosary_set_pet_neck", petseq=1, nick="新昵称")):
            before = copy.deepcopy(server.PLAYER_STATE)
            server._save_player_state()
            disk = Path(server.STATE_FILE).read_bytes()
            with patch.object(server.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    action()
            self.assertEqual(server.PLAYER_STATE, before)
            self.assertEqual(Path(server.STATE_FILE).read_bytes(), disk)
            self.assertEqual(list(Path(server.STATE_FILE).parent.glob("*.tmp")), [])

    def test_upgraded_pot_changes_real_growth_and_harvest(self):
        self.prepare_smelt()
        server.PLAYER_STATE["active_decorations"]["pot0"] = 120705048
        server.PLAYER_STATE["activities"]["smelt_pots"] = {
            "120705048": {"speed": 1000, "addon": 1500, "exp": 2000, "charm": 2000}}
        server.PLAYER_STATE["seeds"][26078] = 1
        self.assertEqual(self.call("rosary0904_soil_plant_rose", soilno=1, rosetype=28078)["result"], 0)
        flower = server._flowers()[28078]
        maturity = float(flower["times"].split(",")[-1]) * 60 * .9
        with patch.object(server.time, "time", return_value=NOW + maturity):
            initial = server.handle_cmd("rosary0908_get_plant_info_self", {})
            response = server.handle_cmd("rosary0904_gain", {"soilno": 1})
        self.assertEqual(initial["soil1"][0]["local_grow_speed"], 10)
        self.assertEqual(response["result"], 0, response)
        self.assertEqual(response["igainrosecount"], 35)
        self.assertEqual((response["addexperice"], response["addcharm"]), (207, 21))
        self.assert_saved()

    def test_unknown_operations_never_return_or_persist_fake_success(self):
        for cmd, params in (("rosary_unknown", {}), ("rosary_unknown", {"__local_paid": 1}),
                            ("rosary_activity_oper", {"cmd": 999, "request": 2, "paytype": 1})):
            with self.subTest(cmd=cmd, params=params):
                self.assert_rejected_without_changes(lambda: self.call(cmd, **params))
                self.assertTrue(self.call(cmd, **params)["local_unsupported"])

    def fairy(self, operation, **params):
        return self.call("rosary0904_expand", action=6, actionop=operation, soilno=9, **params)

    def prepare_fairy(self):
        self.assertEqual(self.fairy(1)["result"], 0)
        server.PLAYER_STATE["props"].update({31005: 10, 31020: 5})
        server.PLAYER_STATE["rosemoney"] = 100000
        return server.PLAYER_STATE["pots"][9]

    def test_fairy_unlock_and_level_refine_have_complete_client_fields(self):
        pot = self.prepare_fairy()
        initial = self.call("rosary0908_get_plant_info_self")["soil9"][0]
        self.assertEqual(initial["hanglevel"], 0)
        self.assertEqual(initial["need"]["stone"], 1)
        self.assertEqual(initial["attrneed"]["material"][0]["id"], 31020)
        pot["hangpercent"] = 99
        response = self.fairy(3, stoneid=31005)
        self.assertEqual(response["result"], 0, response)
        self.assertEqual((response["refsucc"], response["hanglevel"], response["hangpercent"]), (1, 1, 0))
        self.assertEqual(response["change"], {"stone": -1, "material": [{"type": 6, "id": 1001, "count": -1000}]})
        self.assertEqual(server.PLAYER_STATE["rosemoney"], 99000)
        self.assertEqual(server.PLAYER_STATE["props"][31005], 9)
        self.assertEqual(response["need"]["material"][0]["count"], 2000)
        self.assert_saved()

    def test_fairy_attribute_refine_preview_discard_commit_and_reload(self):
        pot = self.prepare_fairy()
        pot["potlevel"] = 1
        response = self.fairy(4, stoneid=31005)
        self.assertEqual(response["refsucc"], 1)
        self.assertEqual(response["hpattribute"], {"speed": 10, "increase": 0, "charm": 0, "exp": 0})
        self.assertEqual(server.PLAYER_STATE["props"][31020], 4)
        original = dict(pot["hpattribute"])
        preview = self.fairy(5)
        self.assertNotEqual(preview["hpattribute"], original)
        self.assertEqual(pot["hpattribute"], original, "Preview must not equip attributes")
        self.assert_saved()
        self.assertEqual(self.fairy(7)["hpattribute"], original)
        preview = self.fairy(5)
        loaded = server._load_player_state()
        server.PLAYER_STATE.clear()
        server.PLAYER_STATE.update(loaded)
        committed = self.fairy(6)
        self.assertEqual(committed["hpattribute"], preview["hpattribute"])
        self.assertNotIn("pending_hpattribute", server.PLAYER_STATE["pots"][9])
        self.assert_saved()

    def test_fairy_failure_consumes_only_declared_costs_and_retains_progress(self):
        pot = self.prepare_fairy()
        pot.update(hangpercent=95, refine_attempts=2)
        result = self.fairy(3, stoneid=31005)
        self.assertEqual((result["result"], result["refsucc"], result["hangpercent"]), (0, 0, 95))
        self.assertEqual(server.PLAYER_STATE["props"][31005], 9)
        self.assertEqual(server.PLAYER_STATE["rosemoney"], 99000)
        self.assert_saved()

    def test_fairy_invalid_orders_and_caps_do_not_consume_materials(self):
        pot = self.prepare_fairy()
        self.assert_rejected_without_changes(lambda: self.fairy(4, stoneid=31005))
        self.assert_rejected_without_changes(lambda: self.fairy(3, stoneid=99))
        self.assert_rejected_without_changes(lambda: self.fairy(6))
        self.assert_rejected_without_changes(lambda: self.fairy(99))
        pot = server.PLAYER_STATE["pots"][9]
        pot["potlevel"] = 4
        self.assert_rejected_without_changes(lambda: self.fairy(3, stoneid=31005))
        pot = server.PLAYER_STATE["pots"][9]
        pot["hpattribute"] = {key: 200 for key in gameplay.FAIRY_ATTRIBUTES}
        self.assert_rejected_without_changes(lambda: self.fairy(4, stoneid=31005))

    def test_fairy_save_replace_failure_restores_materials_and_pending_state(self):
        self.prepare_fairy()
        server._save_player_state()
        before = copy.deepcopy(server.PLAYER_STATE)
        with patch.object(server.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.fairy(3, stoneid=31005)
        self.assertEqual(server.PLAYER_STATE, before)
        self.assert_saved()

    def test_unimplemented_gem_operation_is_rejected_instead_of_acknowledged(self):
        self.assert_rejected_without_changes(lambda: self.call("rosary0904_expand", action=4, gemop=1, soilno=1))


if __name__ == "__main__":
    unittest.main()
