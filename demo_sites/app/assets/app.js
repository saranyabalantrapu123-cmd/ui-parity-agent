// Small progressive enhancements shared by the Nimbus Wireless demo sites.
(function () {
  // Floating assistant launcher: toggle the chat window.
  document.querySelectorAll(".chat-launcher__btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var win = btn.parentElement.querySelector(".chat-window");
      if (!win) return;
      win.hidden = !win.hidden;
      btn.setAttribute("aria-expanded", String(!win.hidden));
    });
  });

  // Echo query-string values (selected plan, payment amount) into the page.
  var params = new URLSearchParams(window.location.search);
  var plans = { essentials: "Essentials", unlimited: "Unlimited", plus: "Unlimited Plus" };
  document.querySelectorAll("[data-echo]").forEach(function (el) {
    var key = el.getAttribute("data-echo");
    var value = params.get(key);
    if (!value) return;
    if (key === "plan") value = plans[value] || value;
    if (key === "amount") value = "$" + Number(value).toFixed(2);
    if (el.tagName === "INPUT") el.value = params.get(key); else el.textContent = value;
  });

  // Trade-in estimator (web only): fake, deterministic estimate.
  var estimate = document.getElementById("trade-estimate");
  var estimateBtn = document.getElementById("trade-estimate-btn");
  if (estimate && estimateBtn) {
    estimateBtn.addEventListener("click", function () {
      var cond = document.getElementById("trade-condition").value;
      var base = { good: 200, fair: 120, poor: 40 }[cond] || 0;
      estimate.textContent = "Estimated credit: $" + base;
    });
  }
})();
