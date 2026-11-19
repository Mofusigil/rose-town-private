// Execute the actual mirrored modules to cover initialization regressions.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
process.on("uncaughtException", error => { console.error(error.stack); process.exitCode = 1; });
const root = path.resolve(__dirname, "../site/h5/meigui");
const decorators = new Proxy({}, { get: () => () => () => {} });
function Base() {}
const userType = function UserData() {};
const models = { UserData: userType, SpecialProps: function SpecialProps() {},
  UserDataUitls: { isExclusivecard: () => false } };
const messages = [];
const context = vm.createContext({
  window: {}, Map, Promise, console,
  cc: { _RF: { push() {}, pop() {} }, Node: { EventType: {} } },
  Milkytea: { Model: Base, ReferenceModel: Base, Controller: Base, View: Base, ViewModel: Base,
    Canvas: Base, BinderCanvas: Base, Module: Base, Decorators: decorators,
    SerializeType: {}, FairyguiEvent: {}, FairyguiType: {}, Binder: {}, Log() {},
    Modules: { Scene: {} } },
  Rose: { Models: models, Decorators: decorators,
    Settings: { Layers: {}, Scene: {}, RosarySeverUrl: {}, HttpSettings: {},
      AssetBundleName: {}, UIAssetName: {} },
    Utils: { Canvas: {}, ReportUtils: {
      BuriedPointLocalStorage: {}, actionReport() {} } },
    Alert: { MessageBoxType: {}, ShowMessage: (_, text) => messages.push(text),
      ShowSimpleMsg: text => messages.push(text) } },
  fairygui: { GComponent: Base, Event: {} }
});
vm.runInContext(fs.readFileSync(path.join(root, "lib/shop-fixes.js"), "utf8"), context);
context.RoseShopFixes = context.window.RoseShopFixes;
function loadBundle(file) {
  const code = fs.readFileSync(path.join(root, file), "utf8");
  const inert = code.replace(/,\{\},\[[\s\S]*\]\);\s*$/, ",{},[]);");
  assert.notEqual(code, inert, "Disable only bundle entrypoints in the harness");
  vm.runInContext(inert, context, { filename: file });
  context.__require = context.window.__require;
  return context.__require;
}
const main = loadBundle("assets/main/index.57d00.js");

const BottomNavigation = main("BottomNavigation").BottomNavigation;
const PropsManager = main("PropsManager").PropsManager;
context.Rose.Settings.AssetBundleName = {UI: "UI", SenceDecoration: "SenceDecorationRes"};
context.Rose.Settings.UIAssetName = {UI: "UI"};
for (const missing of [undefined, null, NaN, Infinity, -1, "invalid", 1.5, 0, "0", 161437001]) {
  const navigation = new BottomNavigation(missing);
  assert.equal(navigation._bundleStr, "UI");
  assert.equal(navigation._pathStr, "UI");
  assert.equal(navigation._userParams, "bottom_init");
}
for (const theme of [161437002, "161437052"]) {
  const navigation = new BottomNavigation(theme);
  assert.equal(navigation._bundleStr, "SenceDecorationRes");
  assert.equal(navigation._pathStr, "roseLifeFrame_" + theme);
  assert.equal(navigation._userParams, "bottom_" + theme);
}

const warnings = [];
context.Milkytea.Warn = text => warnings.push(text);
context.Milkytea.Error = text => { throw new Error(text); };
models.NumberedPropsModel = {isNumberPropById: () => false};
models.PropAwardType = {AT_DECORATION: 4};
const pot = {};
const props = Object.assign(Object.create(PropsManager.prototype), {decorateProps: new Map([[123, pot]])});
props.onInitFlowerPotProps({
  fpot: [{pot123: [{type: 123, eday: 3}]}], special_pots: [], pots: [],
  pot123extra: [99, 99], jackpot: [99, 99], pot123: [1, 0], sendable: {pot: [123]}
});
assert.deepEqual(pot, {count: 1, usedCount: 0, isPresent: 0});
assert.deepEqual(warnings, [], "Container fields must not be parsed as numeric pot IDs");
props.onInitFlowerPotProps({pot123: [0, 0]});
assert.equal(pot.count, 0, "Zero inventory must update normally");
props.onInitFlowerPotProps({pot999: [1, 0]});
assert.equal(warnings.length, 1, "A genuine unknown numeric pot must still be reported");
assert(warnings[0].endsWith("999"));
props.pareseTimeLimitPot({fpot: [{soil: 123, pot123: [{type: 123, eday: 3}]}]});
assert.equal(pot.isGloabalDecorate, true);
assert.equal(pot.remainingDay, 3);

// Smelting speed uses a private copy of the flower's cumulative stage times.
const FlowerPotData = main("FlowerPotData").FlowerPotData;
const originalTimes = [600, 1200, 1800, 2400];
const seed = {times: originalTimes, plantMc: "seed", id: 28078, name: "测试花", season: 1};
const flowerPot = Object.assign(Object.create(FlowerPotData.prototype), {
  flowerInfo: {}, getModel: () => ({getFlowerById: () => seed})
});
flowerPot._onFlowerPotState({soilstate: 28078, season: 1, local_grow_speed: 10});
assert.deepEqual(Array.from(flowerPot._growupTimes), [540, 1080, 1620, 2160]);
assert.deepEqual(originalTimes, [600, 1200, 1800, 2400], "Shared flower configuration stays unchanged");
flowerPot._onFlowerPotState({soilstate: 28078, season: 1});
assert.equal(flowerPot._growupTimes, originalTimes);

// Older local renewals have no optional avatar ID. Use the shipped default
// pet package and its component rather than requesting a non-existent "0".
const PetData = main("PetData").PetData;
for (let id = 1; id <= 6; id++) {
  const pet = Object.assign(Object.create(PetData.prototype), {
    id, avatarId: 0, physicalStrength: 100, effectiveDay: 30
  });
  assert.equal(pet.getPetUrl2(), `pet_${id}_normal`);
  assert.equal(pet.getPetResName2(), "Main_1_1");
  pet.avatarId = 300003355;
  assert.equal(pet.getPetUrl2(), "300003355");
  assert.equal(pet.getPetResName2(), "Main");
}

// Preview and gateway share the explicitly local 100-exp-per-level curve.
const smelt = loadBundle("assets/SmeltPot/index.82579.js");
const ChooseMaterial = smelt("SmeltPotChooseMaterialModel").SmeltPotChooseMaterialModel;
for (const [tab, total, gain, expected] of [
  [0, 0, 100, 0], [0, 0, 1000, 200], [0, 750, 200, 150],
  [0, 950, 200, 50], [0, 1000, 200, 0], [1, 1400, 1000, 100],
  [2, 850, 100, 50], [3, 1900, 1000, 100]
]) {
  const chooser = Object.assign(Object.create(ChooseMaterial.prototype), {
    curTab: tab, curAddonData: {exp: total}, smeltValue: gain,
    getModel: () => ({costMinLvelArr: [8, 8, 9, 9]})
  });
  assert.equal(chooser.getNeedStoneCount(), expected, `Stone preview for tab ${tab}, ${total} + ${gain}`);
}
const orders = loadBundle("assets/FlowerOrder/index.0b031.js");
const FlowerOrderCtrl = orders("FlowerOrderCtrl").FlowerOrderCtrl;
const orderMessages = [];
const orderCtrl = Object.assign(Object.create(FlowerOrderCtrl.prototype), {
  showMessaage: text => orderMessages.push(text)
});
const unavailable = {result: 2, resultstr: "该玩法尚未实现本地协议", local_unsupported: true};
orderCtrl._onPotExpand({response: unavailable, userParams: {cmd: "FlowerOrder", showCanvas: false}});
assert.equal(orderMessages.length, 0, "An optional background probe must not block initial login");
orderCtrl._onPotExpand({response: unavailable, userParams: {cmd: "FlowerOrder", showCanvas: true}});
assert.deepEqual(orderMessages, [unavailable.resultstr], "An explicit operation reports unavailable gameplay");

// The activity entry point contains a second copy of the same shared modules.
const alternate = loadBundle("act/main/assets/main/index.951ed.js");
const AlternateNavigation = alternate("BottomNavigation").BottomNavigation;
assert.equal(new AlternateNavigation(undefined)._userParams, "bottom_init");
const AlternateProps = alternate("PropsManager").PropsManager;
const alternatePot = {};
const alternateProps = Object.assign(Object.create(AlternateProps.prototype), {decorateProps: new Map([[123, alternatePot]])});
alternateProps.onInitFlowerPotProps({fpot: [], special_pots: [], pot123: [1, 1]});
assert.deepEqual(alternatePot, {count: 1, usedCount: 1});
assert.equal(warnings.length, 1, "Activity entry must also ignore fpot containers");

// Warehouse is shared by several scenes. Start the smelting module before
// dispatching the click, including when opening it from the baby's room.
const warehouse = loadBundle("assets/Warehouse/index.cd9c5.js");
const WarehouseView = warehouse("WarehouseView").WarehouseView;
const started = [], dispatched = [];
const prop = {id: 120705048};
context.Rose.SmeltPot = {Name: "SmeltPotModule", Message: {showSmeltPot: "showSmeltPot"}};
context.Rose.Start = name => {started.push(name); return Promise.resolve();};
const warehouseView = Object.assign(Object.create(WarehouseView.prototype), {
  _mainCanvas: {closeWarehouseCanvas() {}},
  getModel: () => ({decorateProps: new Map([[prop.id, prop]])}),
  cast: (...args) => dispatched.push(args)
});
warehouseView.onItemClick({getUserData: () => [prop.id, 4, "smeltPot"]});
assert.deepEqual(started, ["SmeltPot"]);
assert.equal(dispatched.length, 0, "Wait for module loading before dispatch");
Promise.resolve().then(() => {
  assert.deepEqual(dispatched, [["SmeltPotModule", "showSmeltPot", prop]]);
  console.log("Runtime client checks passed (navigation, pot fields, growth, smelting preview and startup, background probes)");
});
