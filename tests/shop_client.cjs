// Regression checks execute the shipped bundle methods in a small framework
// harness; browser checks separately verify the real FairyGUI dialogs.
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
  Milkytea: { Model: Base, ReferenceModel: Base, Controller: Base, View: Base,
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
const shopDataExports = main("ShopData");
models.ShopData = shopDataExports.ShopData;
models.ShopPropType = shopDataExports.ShopPropType;
models.ShopDataPropertys = shopDataExports.ShopDataPropertys;
models.UserDataPropertys = {};
models.CharmFlowerArr = shopDataExports.CharmFlowerArr;
models.CharmLevelManager = main("CharmLevelManager").CharmLevelManager;
models.FlowerManager = main("FlowerManager").FlowerManager;
const charm = new models.CharmLevelManager();
const data = new models.ShopData();
data.getModel = () => charm;
const fixes = context.RoseShopFixes;

// Missing dynamic data, zero, numeric strings and malformed partial arrays.
for (const bad of [undefined, null, "", "  ", NaN, Infinity, -1, "invalid", false]) {
  assert.equal(fixes.formatCharm(bad), "以赠送结果为准");
}
assert.equal(fixes.formatCharm(0), "+0");
assert.equal(fixes.resolveCharm(0, 123), 0);
assert.equal(fixes.resolveCharm(undefined, "12"), 12);
charm.setSpecialCharm({ valentinesDay2020sndCharm: [0, "12", null, "bad"],
  valentinesDay2020rcvCharm: [6, 24] });
assert.equal(charm.getSendCharm(models.CharmFlowerArr[0]), 0);
assert.equal(charm.getSendCharm(models.CharmFlowerArr[1]), 12);
assert.equal(charm.getSendCharm(models.CharmFlowerArr[2]), undefined);
assert.equal(charm.getRecvCharm(models.CharmFlowerArr[2]), undefined);

// All eight ordinary bouquets retain their documented send/receive values.
const values = [[3,6], [6,12], [9,18], [15,30], [30,60], [90,180], [180,360], [300,600]];
for (const [index, [send, recv]] of values.entries()) {
  const tips = data.getCharmFlowerTips({ id: 41 + index, name: "普通花束",
    givercharm: send, charm: recv, gift: "金币", info: "花语" });
  assert(tips.includes("+" + send + "[color]"));
  assert(tips.includes("+" + recv + "[color]"));
  assert(!/undefined|NaN/.test(tips));
}
for (const id of models.CharmFlowerArr) {
  const tips = data.getCharmFlowerTips({ id, name: "玫瑰", award: "金币", info: "花语" });
  assert(!/undefined|NaN/.test(tips));
}

const shop = loadBundle("assets/Shop/index.b24c8.js");
const ShopView = shop("ShopView").ShopView;
const SendCharmFlowerCanvas = shop("SendCharmFlowerCanvas").SendCharmFlowerCanvas;
const user = { roseMoney: 1000, balance: 50 };
const flower = { id: 28078, seedId: 26078, count: 0, name: "金彗星", seedPriceQPoint: 0 };
const manager = { getFlowerById: id => id === flower.id ? flower : null,
  getFlowerBySeedId: id => id === flower.seedId ? flower : null };
const view = Object.create(ShopView.prototype);
Object.assign(view, { _flowerManager: manager, _userData: user,
  _mainModel: { shopData: { charmFlowers: new Map(), diamond: 50 } },
  getModel: type => type === models.UserData ? user : charm });
let dialog;
view._buyFlowerSeedCanvas = { showDlg: (item, extra) => { dialog = {item, extra}; } };
view.buyProp(flower.id, models.ShopPropType.flower);
assert.equal(dialog.item, flower, "A flower opens even with no market map");
assert.equal(dialog.extra.priceChange, 0);
manager.priceChangeFlower = new Map([[flower.id, 85]]);
view.buyProp(flower.id, models.ShopPropType.flower);
assert.equal(dialog.extra.priceChange, 85);

// Exercise real purchase-response handling, including spending down to zero.
view._onBuySeed({ response: { result: 0, type: flower.seedId, count: 1,
  rosemoneyleft: 0, rosemoneyuse: 1000, balance: 0, discount: 0 } });
assert.equal(user.roseMoney, 0);
assert.equal(user.balance, 0);
assert.equal(flower.count, 1);
assert(!messages.some(text => /undefined|NaN/.test(text)));

// Tooltip and purchase dialog resolve the same values, then render without +undefined.
const special = new models.SpecialProps();
Object.assign(special, { id: models.CharmFlowerArr[2], name: "九十九朵玫瑰",
  priceQPoint: 990, info: "花语", award: "金币" });
view._mainModel.shopData.charmFlowers.set(special.id, special);
view._sendCharmFlowerCanvas = { showDlg: (item, extra) => { dialog = {item, extra}; } };
view.buyProp(special.id, models.ShopPropType.charmFlower);
assert.equal(dialog.extra.sendCharm, null);
assert.equal(dialog.extra.recvCharm, null);
const canvas = Object.create(SendCharmFlowerCanvas.prototype);
Object.assign(canvas, { m_data: special, otherData: dialog.extra,
  txtAll: {}, txtName: {}, getModel: () => ({ isGameVip: false }) });
canvas.setText();
assert(canvas.txtAll.text.includes("赠送人: 魅力 以赠送结果为准"));
assert(canvas.txtAll.text.includes("获赠人: 魅力 以赠送结果为准"));
assert(!/undefined|NaN/.test(canvas.txtAll.text));
special.givercharm = 0;
special.charm = 0;
view.buyProp(special.id, models.ShopPropType.charmFlower);
assert.equal(dialog.extra.sendCharm, 0);
assert.equal(dialog.extra.recvCharm, 0);
canvas.otherData = dialog.extra;
canvas.setText();
assert(canvas.txtAll.text.includes("魅力 +0"));
console.log("Shop client regression checks passed.");
