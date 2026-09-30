/* Dashboard niceties: toasts for saves, copy buttons, and marking the open tab. No dependencies. */
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
    var timer = setTimeout(dismiss, 5200);
    el.addEventListener("click", dismiss);
    function dismiss() {
      clearTimeout(timer);
      el.classList.remove("in");
      setTimeout(function () { el.remove(); }, reduceMotion ? 0 : 250);
    }
  }

  // Copy buttons: <button class="copy-btn" data-copy="...">Coped text lands on the clipboard.
  document.addEventListener("click", function (event) {
    var btn = event.target.closest(".copy-btn");
    if (!btn) return;
    var done = function () {
      var before = btn.textContent;
      btn.textContent = "Copied";
      btn.disabled = true;
      setTimeout(function () { btn.textContent = before; btn.disabled = false; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(btn.dataset.copy).then(done, done);
    } else { done(); }
  });

  // Mark the tab (topbar or business nav) whose href matches the open page.
  var here = location.pathname.replace(/\/$/, "") || "/";
  document.querySelectorAll(".topbar-nav a, nav.tabs a").forEach(function (a) {
    var target = (new URL(a.href, location.origin)).pathname.replace(/\/$/, "") || "/";
    if (target === here || here.indexOf(target + "/") === 0) a.setAttribute("aria-current", "page");
  });
})();
