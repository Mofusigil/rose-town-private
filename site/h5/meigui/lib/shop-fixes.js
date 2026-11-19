// Shared formatting for shop values supplied by configuration or the gateway.
(function (root) {
  "use strict";

  function charmNumber(value) {
    if (value === null || value === undefined || value === "" ||
        (typeof value !== "number" && typeof value !== "string")) return null;
    if (typeof value === "string" && !value.trim()) return null;
    var number = Number(value);
    return isFinite(number) && number >= 0 ? number : null;
  }

  root.RoseShopFixes = {
    resolveCharm: function (configured, supplied) {
      var number = charmNumber(configured);
      return number === null ? charmNumber(supplied) : number;
    },
    formatCharm: function (value) {
      var number = charmNumber(value);
      return number === null ? "以赠送结果为准" : "+" + number;
    },
    setCharmValues: function (map, ids, values) {
      if (!Array.isArray(values)) return;
      ids.forEach(function (id, index) {
        var number = charmNumber(values[index]);
        if (number === null) map.delete(id);
        else map.set(id, number);
      });
    }
  };
})(window);
