// Execute shipped methods, including the real response parser, rather than
// merely checking that bundle source contains a private-server hook.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
process.on("uncaughtException", error => { console.error(error.stack); process.exitCode = 1; });
const root = path.resolve(__dirname, "../site/h5/meigui");
function Base() {}
const decorators = new Proxy({}, { get: () => () => () => {} });
const UserData = function UserData() {};
const ShopData = function ShopData() {};
const user = { balance: 0, roseMoney: 0, gameVipLevel: 0 };
const shopData = { diamond: 0, specialProps: new Map(), charmFlowers: new Map() };
const notifications = [], dialogs = [], requests = [], messages = [];
const userTypes = new Set([UserData]);
const modelSystem = { get: type => userTypes.has(type) ? user : type === ShopData ? shopData : null };
const context = vm.createContext({
  Map, Promise, console, URL, Number, Date,
  location: { href: "http://localhost:8088/index.html", origin: "http://localhost:8088" },
  cc: { _RF: { push() {}, pop() {} }, Node: { EventType: {} }, sys: {
    openURL: url => { throw new Error("Unexpected external payment: " + url); } } },
  Kernel: { System: Base, Component: Base, ListenerComponent: Base, ReferenceSystem: Base, AgentComponent: Base },
  Framework: { ModelSystem: {} },
  Milkytea: { Model: Base, ReferenceModel: Base, Controller: Base, View: Base,
    Canvas: Base, BinderCanvas: Base, Module: Base, Decorators: decorators,
    SerializeType: {}, FairyguiEvent: {}, FairyguiType: {}, Binder: {}, Log() {},
    HttpRequest: { POST: "post" }, Modules: { Scene: {} },
    CastModule: (...args) => dialogs.push(args) },
  Rose: { Models: { UserData, ShopData, SpecialProps: Base,
      UserDataUitls: { isExclusivecard: () => false } }, Decorators: decorators,
    Settings: { Layers: {}, Scene: {}, HttpSettings: { host: "http://localhost:8088/" },
      RosarySeverUrl: { BuySeedWithGold: "gold_seed", BuySeedWithQB: "paid_seed", BuyGameProps: "buy_props",
        BuyFertilizer: "buy_fertilizer", BuyGmaePropsOther: "buy_other", GameVip: "rosary_activity_oper" },
      AssetBundleName: {}, UIAssetName: {} },
    Utils: { Canvas: {}, ReportUtils: { BuriedPointLocalStorage: {}, actionReport() {} },
      ServerRewardUtils: { updateReward() {} } },
    Plantation: { Name: "Plantation", Message: { BuyVip: "BuyVip" } },
    Alert: { MessageBoxType: {}, ShowMessage: (...args) => dialogs.push(args),
      ShowSimpleMsg: text => messages.push(text) } },
  fairygui: { GComponent: Base, Event: {} }
});
context.window = context;
context.Kernel.System.GetSystem = () => modelSystem;
for (const filename of ["lib/shop-fixes.js", "lib/local-payments.js"]) {
  vm.runInContext(fs.readFileSync(path.join(root, filename), "utf8"), context);
}
function loadBundle(filename) {
  const code = fs.readFileSync(path.join(root, filename), "utf8");
  const inert = code.replace(/,\{\},\[[\s\S]*\]\);\s*$/, ",{},[]);");
  assert.notEqual(code, inert, "Only bundle entrypoints are disabled in this harness");
  vm.runInContext(inert, context, { filename });
  context.__require = context.window.__require;
  return context.__require;
}
const main = loadBundle("assets/main/index.57d00.js");
const shopExports = main("ShopData");
Object.assign(context.Rose.Models, { ShopDataPropertys: shopExports.ShopDataPropertys,
  ShopPropType: shopExports.ShopPropType, UserDataPropertys: {}, CharmFlowerArr: shopExports.CharmFlowerArr });
const payments = context.RoseLocalPayments;
const userExports = main("UserData");
userTypes.add(userExports.UserData);
const balanceUtils = userExports.UserDataUitls;
assert.equal(balanceUtils.CheckBalance(60), false);
assert.equal(payments.afterSpend(100, 30), 70);
payments.observeResponse({ local_free_pay: true, balance: 999 }, "https://baobao.qq.com/cgi-bin/x");
assert.equal(payments.enabled(), false, "An external response never enables local free payments");

// The actual HTTP parser activates free mode and synchronizes the real balance.
const PostLoader = main("PostLoader").PostLoader;
const loader = Object.create(PostLoader.prototype);
loader.url = "http://localhost:8088/cgi-bin/rosary0908_get_user_info";
const parsed = loader.onResponse({ responseText: JSON.stringify({ result: 0, local_free_pay: true, balance: 0 }) });
assert.equal(parsed.response.result, 0);
assert.equal(payments.enabled(), true);
assert.equal(balanceUtils.CheckBalance(6000), true);
assert.equal(user.balance, 0);

// The refining response keeps its alias to UserData; it must not deduct through
// that alias after the common response parser has synchronized the balance.
context.Rose.Utils.ServerRewardUtils.getPropItemNameWithNum = () => "普通灵玉x2";
const refine = loadBundle("assets/FairyPotRefine/index.67530.js");
const refineCtrl = Object.create(refine("FairyPotAttributeCtrl").FairyPotAttributeCtrl.prototype);
Object.assign(refineCtrl, { getModel: type => modelSystem.get(type), showMessaage() {} });
refineCtrl._onBuyAttributeMaterialResponse({ response: { result: 0, id: 31020, num: 2, type: 0 },
  userParams: { cmd: "FairyPotBuyAttributeMaterial", buyPropID: 31020 } });
assert.equal(user.balance, 0, "Spirit jade does not spend through a local user alias");
assert.equal(shopData.diamond, 0);
assert.equal(payments.afterSpend(0, 1000), 0);

const Alert = loadBundle("assets/Alert/index.11790.js")("AlertModule");
let confirmed = 0;
let paidRequest;
Alert.ShowMessage("提示", "是否花费60点券开通VIP？", 0, "确定|取消", event => {
  assert.equal(event.getUserData(), "确定");
  assert.equal(event.detail, "确定");
  confirmed++;
  paidRequest = payments.tagRequest({ route: "/cgi-bin/rosary_activity_oper", data: { cmd: 211, request: 2 } });
});
assert.equal(confirmed, 1);
assert.equal(dialogs.length, 0, "A payment continues without a second confirmation dialog");
assert.equal(paidRequest.data.__local_paid, 1);
Alert.ShowMessage("提示", "是否删除花盆？", 0, "确定|取消", () => { throw new Error("Deleted by payment hook"); });
Alert.ShowMessage("提示", "成功购买1个道具", 0, "确定", () => {});
assert.equal(dialogs.length, 2, "Unrelated confirmations and success dialogs retain their normal behavior");
Alert.ShowMessage("提示", "开通VIP特权需花费60点券", 0, "确定开通|暂不开通", event => {
  assert.equal(event.getUserData(), "确定开通");
  confirmed++;
});
assert.equal(confirmed, 2, "Alternative cancel labels also confirm a paid operation directly");
payments.observeResponse({ result: 0, local_free_pay: true, balance: 0, local_receipt: "activity:buy" }, loader.url);
assert(messages.includes("本地支付成功"), "Generic local purchases visibly acknowledge success");

const query = { route: "/cgi-bin/rosary_activity_oper", data: { cmd: 211, request: 1, paytype: 1 },
  userParams: { cmd: "GetGameVipInfo" } };
payments.tagRequest(query);
assert.equal(query.data.__local_paid, undefined);
assert.equal(query.data.__local_action, "GetGameVipInfo");
payments.notify({ notify() {
  const request = { route: "/cgi-bin/rosary_activity_oper", data: { cmd: 183, request: 2 }, userParams: { cmd: "PinBall" } };
  payments.tagRequest(request);
  assert.equal(request.data.__local_action, "Buy_Request@PinBall");
  assert.equal(request.data.__local_paid, 1);
} }, "Buy_Request@PinBall", ["Buy_Request@PinBall", { count: 1 }]);
const foreign = { route: "https://baobao.qq.com/cgi-bin/rosary_activity_oper", data: {}, userParams: { cmd: "Buy" } };
payments.tagRequest(foreign);
assert.equal(foreign.data.__local_paid, undefined);
const httpSystem = Object.create(main("HttpSystem").HttpSystem.prototype);
Object.assign(httpSystem, { settings: { pretreatmentRequest: (route, data) => [route, data] },
  _requestQueue: [], _looped: true });
const processor = Object.create(main("Processor").Processor.prototype);
processor._module = { notify(action) {
  httpSystem.request({ route: "/cgi-bin/rosary_activity_oper", data: { cmd: 183, request: 2 },
    userParams: { cmd: "PinBall" } });
} };
processor.notify("Buy_Request@PinBall", { count: 1 });
assert.equal(httpSystem._requestQueue[0].data.__local_paid, 1,
  "Real notification and HTTP methods carry a paid activity context");
assert.equal(httpSystem._requestQueue[0].data.__local_action, "Buy_Request@PinBall");
httpSystem.request({ route: "/cgi-bin/rosary_activity_oper", data: { cmd: 183, request: 1 },
  userParams: { cmd: "GetPinBallInfo" } });
assert.equal(httpSystem._requestQueue[1].data.__local_paid, undefined);

// A malformed activity response previously stranded the entire HTTP queue.
// Execute the real queue with a failing listener, then a valid purchase reply.
const completedRoutes = [];
const recoveringHttp = Object.create(main("HttpSystem").HttpSystem.prototype);
Object.assign(recoveringHttp, { settings: { interval: 0 }, _requestQueue: [
  { route: "broken-activity" }, { route: "buy-seed" } ],
  _dispatcher: { notify(route) {
    if (route === "broken-activity") throw new Error("Malformed activity data");
    completedRoutes.push(route);
  } }, _httpRequest: { request(request) {
    request.onComplete({ url: request.route, response: { result: 0 } });
  } } });
assert.throws(() => recoveringHttp.requestLoop(), /Malformed activity data/);
assert.deepEqual(completedRoutes, ["buy-seed"], "A callback error does not block the next purchase");
assert.equal(recoveringHttp._looped, false);

const shop = loadBundle("assets/Shop/index.b24c8.js");
const ShopView = shop("ShopView").ShopView;
const view = Object.create(ShopView.prototype);
Object.assign(view, { _userData: user, _mainModel: { shopData },
  getModel: type => modelSystem.get(type),
  request: (...args) => requests.push(args), showMessaage: text => messages.push(text) });
const paidSeed = { seedId: 26078, seedPriceQPoint: 500, seedPrice: 1000 };
view.onBuySeedBtnClick({ getUserData: () => [paidSeed, 2] });
assert.equal(requests.length, 1, "Paid seeds can be bought with zero points and zero gold");
assert.equal(requests[0][1], "http://localhost:8088/paid_seed");
assert.equal(requests[0][2].count, 2);
view.onBuySeedBtnClick({ getUserData: () => [{ seedId: 26077, seedPrice: 1000, seedPriceQPoint: 0 }, 1] });
assert.equal(requests.length, 1, "Ordinary gold seed spending still checks available gold");
assert(messages.includes("金币不足"));

const prop = { id: 336, priceQPoint: 500, count: 0, name: "道具", unit: "个" };
shopData.specialProps.set(prop.id, prop);
view._onBuyGameProps({ response: { result: 0, id: prop.id, num: 2, discount: 0, balance: 0 },
  userParams: { cmd: "buyShopProps" } });
assert.equal(prop.count, 2, "The shipped success handler grants the item");
assert.equal(user.balance, 0, "The shipped success handler does not locally deduct points");
assert.equal(shopData.diamond, 0);

const BuyTrickWaterCanvas = shop("BuyTrickWaterCanvas").BuyTrickWaterCanvas;
const canvas = Object.create(BuyTrickWaterCanvas.prototype);
Object.assign(canvas, { needDiamod: 100, totalDiamod: 0, m_data: prop, buyCount: 1,
  close() {}, sendCustomEvent: (...args) => notifications.push(args) });
canvas.onBtnOkClick();
assert.equal(notifications.length, 1, "The dialog actually dispatches a purchase with zero points");

const vip = loadBundle("assets/GameVip/index.20d97.js");
const vipView = Object.create(vip("GameVIPBuyView").GameVIPBuyView.prototype);
Object.assign(vipView, { _mainModel: { realPrice: 60, inputCount: 1 }, getModel: type => modelSystem.get(type),
  notify: (...args) => notifications.push(args) });
vipView.onClickVipBuyBtn();
assert.equal(notifications.at(-1)[1].cmd, 211);
assert.equal(notifications.at(-1)[1].request, 2);
const vipCtrl = Object.create(vip("GameVIPCtrl").GameVIPCtrl.prototype);
Object.assign(vipCtrl, { getModel: type => modelSystem.get(type), notify() {}, cast() {} });
vipCtrl._onBuyVipResponse({ response: { result: 0, balance: 0, roseLifeVIP: { level: 1, timeEnd: 2000000000 } },
  userParams: { cmd: "BuyVip@GameVIPCtrl", count: 1 } });
assert.equal(user.roseLifeVIP, 1);
assert.equal(user.roseLifeVIPTimeEnd, 2000000000);
assert.equal(user.balance, 0);

let dailyReward;
vipCtrl.notify = (_, rewards) => { dailyReward = rewards; };
vipCtrl._onGetDailyGiftResponse({ response: { result: 0, gift: [{ addprop506: 2 }] },
  userParams: { cmd: "GetDailyGift@GameVIPCtrl" } });
assert.equal(user.roseLifeGift, 1);
assert.equal(dailyReward[0].id, 506);
assert.equal(dailyReward[0].count, 2);
const vipGiftView = Object.create(vip("GameVIPGetGiftView").GameVIPGetGiftView.prototype);
Object.assign(vipGiftView, { _mainModel: { gameVipData: { gift: 0, validVIPTime: () => true } } });
vipGiftView.updateDailyGiftBtn();
const beforeClaim = vipGiftView._mainModel.dailyGiftStatus;
vipGiftView._mainModel.gameVipData.gift = 1;
vipGiftView.updateDailyGiftBtn();
assert.notEqual(vipGiftView._mainModel.dailyGiftStatus, beforeClaim,
  "The real VIP view enables an active member's daily reward and marks it claimed afterwards");

// Validate every changed shipped bundle without launching its entrypoints.
let syntaxCount = 0;
function inspect(directory) {
  for (const name of fs.readdirSync(directory, { withFileTypes: true })) {
    const filename = path.join(directory, name.name);
    if (name.isDirectory()) inspect(filename);
    else if (name.name.endsWith(".js")) {
      const code = fs.readFileSync(filename, "utf8");
      if (code.includes("RoseLocalPayments.")) {
        try { new vm.Script(code, { filename }); }
        catch (error) { throw new Error(`${filename}: ${error.message}`); }
        syntaxCount++;
      }
    }
  }
}
inspect(path.join(root, "assets"));
inspect(path.join(root, "act/main/assets"));
assert(syntaxCount >= 35);

(async () => {
  const actualFetches = [];
  context.fetch = async (url, options) => {
    actualFetches.push({ url, options });
    return { ok: true, json: async () => ({ result: 0, local_free_pay: true, balance: 300 }) };
  };
  const manager = Object.create(main("GameVIPManager").GameVIPManager.prototype);
  await manager.payCoin(300);
  assert.equal(actualFetches[0].url, "http://localhost:8088/local_payments");
  assert.equal(JSON.parse(actualFetches[0].options.body).count, 300);
  assert.equal(user.balance, 300);
  assert.equal(shopData.diamond, 300);
  context.fetch = async () => ({ ok: false });
  assert.equal(await payments.recharge(100), false);
  assert.equal(user.balance, 300, "A failed local request never grants currency");
  console.log(`Payment client checks passed; ${syntaxCount} patched bundle syntax checks passed.`);
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
