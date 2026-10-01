/* Dashboard niceties: toasts, copy buttons, the current tab, confirmations, busy buttons. No dependencies. */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Toasts: the server puts the confirmation into #toasts[data-ok]; show it briefly.
  var host = document.getElementById("toasts");
  if (host && host.dataset.ok) {
    toast(host.dataset.ok, "ok");
  }

  function toast(text, kind) {
    var el = document.createElement("div");
    el.className = "toast " + kind;
    var dot = document.createElement("span");
    dot.className = "dot";
    dot.setAttribute("aria-hidden", "true");
    el.appendChild(dot);
    el.appendChild(document.createTextNode(text));
    el.title = "Dismiss";
    host.appendChild(el);
    requestAnimationFrame(function () { el.classList.add("in"); });
    var timer = setTimeout(dismiss, 5000);
    el.addEventListener("click", dismiss);
    function dismiss() {
      clearTimeout(timer);
      el.classList.remove("in");
      setTimeout(function () { el.remove(); }, reduceMotion ? 0 : 250);
    }
  }

  // A page that failed to save shows its error at the top: move focus there so it is read out.
  var problem = document.getElementById("page-error");
  if (problem) problem.focus();

  // Copy buttons: <button class="copy-btn" data-copy="...">. Without clipboard access, select the text instead.
  document.addEventListener("click", function (event) {
    var btn = event.target.closest(".copy-btn");
    if (!btn) return;
    var before = btn.textContent;
    var show = function (label) {
      btn.textContent = label;
      setTimeout(function () { btn.textContent = before; }, 1800);
    };
    var selectText = function () {
      var code = btn.parentElement && btn.parentElement.querySelector("code");
      if (code) {
        var range = document.createRange();
        range.selectNodeContents(code);
        var selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
      show("Press Ctrl+C");
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(btn.dataset.copy).then(function () { show("Copied"); }, selectText);
    } else {
      selectText();
    }
  });

  // Mark the open page's tab in each nav: the longest matching link, so "Home" isn't lit on every page.
  var here = location.pathname.replace(/\/$/, "") || "/";
  document.querySelectorAll(".topbar-nav, nav.tabs").forEach(function (nav) {
    var best = null;
    var bestLength = -1;
    nav.querySelectorAll("a").forEach(function (a) {
      var url = new URL(a.href, location.origin);
      if (url.origin !== location.origin) return;
      var target = url.pathname.replace(/\/$/, "") || "/";
      var matches = target === here || here.indexOf(target + "/") === 0;
      if (matches && target.length > bestLength) {
        best = a;
        bestLength = target.length;
      }
    });
    if (best) best.setAttribute("aria-current", "page");
  });

  // Destructive actions: data-confirm="question" on the button (or its form) asks first.
  // Then the pressed button shows it's working and the form can't be sent twice.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var button = event.submitter;
    var question = (button && button.dataset.confirm) || form.dataset.confirm;
    if (question && !window.confirm(question)) {
      event.preventDefault();
      return;
    }
    if (button) button.setAttribute("aria-busy", "true");
    // Disable after this tick, so the pressed button's name and value still go with the form.
    setTimeout(function () {
      form.querySelectorAll("button[type=submit], button:not([type])").forEach(function (b) { b.disabled = true; });
    }, 0);
  });

  // Back to a page kept in memory: undo the busy state so its buttons work again.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    document.querySelectorAll("[aria-busy=true]").forEach(function (b) { b.removeAttribute("aria-busy"); });
    document.querySelectorAll("form button[disabled]").forEach(function (b) { b.disabled = false; });
  });
})();
