/* Local private-server payments. Enabled by a same-origin server response only. */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.RoseLocalPayments = api;
})(typeof window === "object" ? window : globalThis, function (root) {
  "use strict";
  var free = false;
  var paymentContext = null;

  function sameOrigin(url) {
    try {
      return Boolean(root.location &&
        new URL(url, root.location.href).origin === root.location.origin);
    } catch (_) { return false; }
  }

  function model(type) {
    try {
      return root.Kernel.System.GetSystem(root.Framework.ModelSystem).get(type);
    } catch (_) { return null; }
  }

  function syncBalance(response) {
    if (!response || response.balance == null || !root.Rose || !root.Rose.Models) return;
    var balance = Number(response.balance);
    if (!Number.isFinite(balance) || balance < 0) return;
    var user = model(root.Rose.Models.UserData);
    if (user) user.balance = balance;
    var shop = model(root.Rose.Models.ShopData);
    if (shop) shop.diamond = balance;
  }

  function observeResponse(response, url) {
    if (!response || !sameOrigin(url)) return;
    if (response.local_free_pay === true) free = true;
    else if (response.local_free_pay === false) free = false;
    if (free) {
      syncBalance(response);
      if (Number(response.result) === 0 && response.local_receipt) showResult("本地支付成功");
    }
  }

  function canAfford(balance, price) {
    return free || Number(balance) >= Number(price);
  }

  function afterSpend(balance, price) {
    return free ? balance : Number(balance) - Number(price);
  }

  function isPaidAction(action, data) {
    action = String(action || "");
    if (/get|query|init|show|info|response|help|tips|config/i.test(action)) return false;
    if (/buy|purchase|renew|recharge|pay|spend|directupgrade/i.test(action)) return true;
    return Boolean(data && (Number(data.paytype) === 1 || Number(data.is_pay) === 1 || Number(data.autoPay) === 1 ||
      Number(data.autoBuy) === 1 || Number(data.auto_buy) === 1));
  }

  function withPayment(action, callback) {
    var previous = paymentContext;
    paymentContext = action;
    try { return callback(); }
    finally { paymentContext = previous; }
  }

  function notify(target, action, args) {
    if (free && isPaidAction(action, args[1])) {
      return withPayment(String(action), function () { return target.notify.apply(target, args); });
    }
    return target.notify.apply(target, args);
  }

  function tagRequest(request) {
    if (!free || !request || !request.data || !sameOrigin(request.route)) return request;
    var action = paymentContext || (request.userParams && request.userParams.cmd) || "";
    if (action) request.data.__local_action = String(action);
    if (paymentContext || isPaidAction(action, request.data)) request.data.__local_paid = 1;
    return request;
  }

  function confirmPayment(text, buttons, callback) {
    if (!free || typeof callback !== "function") return false;
    var labels = String(buttons || "").split("|");
    var negative = /取消|cancel|暂不|不要|不买|不了|返回|再说|以后|稍后|放弃/i;
    if (labels.length < 2 || !labels.some(function (label) { return negative.test(label); })) return false;
    var plain = String(text || "").replace(/<[^>]*>|\[[^\]]*\]/g, "");
    if (/删除|丢弃|卖出|出售|清空|销毁/.test(plain)) return false;
    if (!/点券|点卷|Q币|QB|购买|续费|开通|充值|支付|付费|花费|消耗/.test(plain)) return false;
    var label = labels.find(function (entry) { return !negative.test(entry); });
    if (!label) return false;
    var event = { detail: label, getUserData: function () { return label; }, stopPropagation: function () {} };
    withPayment("payment-confirmation", function () { callback(event); });
    return true;
  }

  function showResult(text) {
    if (root.Rose && root.Rose.Alert && root.Rose.Alert.ShowSimpleMsg) root.Rose.Alert.ShowSimpleMsg(text);
  }

  function recharge(count) {
    if (!free || !root.location || typeof root.fetch !== "function") return Promise.resolve(false);
    count = Math.min(1000000, Math.max(1, Math.ceil(Math.abs(Number(count) || 100))));
    return root.fetch(new URL("/local_payments", root.location.href).href, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "recharge", count: count })
    }).then(function (response) {
      if (!response.ok) throw new Error("本地点券领取失败");
      return response.json();
    }).then(function (response) {
      if (Number(response.result) !== 0 || response.local_free_pay !== true) {
        throw new Error(response.resultstr || "本地点券领取失败");
      }
      observeResponse(response, root.location.href);
      showResult("本地点券已到账");
      return response;
    }).catch(function (error) {
      showResult(error.message || "本地点券领取失败");
      return false;
    });
  }

  return { enabled: function () { return free; }, observeResponse: observeResponse,
    canAfford: canAfford, afterSpend: afterSpend, confirmPayment: confirmPayment,
    notify: notify, tagRequest: tagRequest, recharge: recharge };
});
