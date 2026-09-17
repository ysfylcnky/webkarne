/* WebKarne — the small vanilla JS the interface needs (DESIGN-SYSTEM § 14).
   Progressive enhancement: with JS off, finding rows simply do not expand.
   Scope for now: accordion (in-place finding expansion), copy buttons, and the
   expand/collapse-all toolbar. Term tooltips and live-progress come later. */
(function () {
  "use strict";

  function setOpen(control, open) {
    var head = control.querySelector(".control__head");
    control.classList.toggle("is-open", open);
    if (head) head.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function toggle(control) {
    var open = !control.classList.contains("is-open");
    setOpen(control, open);
    var head = control.querySelector(".control__head");
    if (open && head && head.dataset.anchor) {
      history.replaceState(null, "", "#" + head.dataset.anchor);
    }
  }

  function copy(btn) {
    var text = btn.getAttribute("data-copy");
    if (!text) return;
    var done = function () {
      var label = btn.getAttribute("data-copied");
      if (!label) return;
      var prev = btn.getAttribute("aria-label");
      btn.classList.add("is-copied");
      btn.setAttribute("aria-label", label);
      setTimeout(function () {
        btn.classList.remove("is-copied");
        if (prev) btn.setAttribute("aria-label", prev);
      }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else {
      fallback();
    }
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "absolute";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        done();
      } catch (e) {
        /* clipboard unavailable — leave the record on screen to copy by hand */
      }
      document.body.removeChild(ta);
    }
  }

  function toggleAll() {
    var controls = Array.prototype.slice.call(
      document.querySelectorAll(".control--expandable")
    );
    var anyClosed = controls.some(function (c) {
      return !c.classList.contains("is-open");
    });
    controls.forEach(function (c) {
      setOpen(c, anyClosed);
    });
  }

  document.addEventListener("click", function (e) {
    var head = e.target.closest && e.target.closest(".control__head");
    if (head) {
      toggle(head.closest(".control--expandable"));
      return;
    }
    var copyBtn = e.target.closest && e.target.closest("[data-copy]");
    if (copyBtn) {
      e.preventDefault();
      copy(copyBtn);
      return;
    }
    var all = e.target.closest && e.target.closest("[data-toggle-all]");
    if (all) {
      e.preventDefault();
      toggleAll();
      return;
    }
    // "Download PDF" = the browser's own print-to-PDF over the print stylesheet
    // (§ 8; no server-side PDF). Progressive enhancement: with JS off the link is
    // inert rather than misleading.
    var printBtn = e.target.closest && e.target.closest("[data-print]");
    if (printBtn) {
      e.preventDefault();
      window.print();
    }
  });

  // Anchor strip (finding page): highlight the section currently in view.
  function initScrollSpy() {
    var strip = document.querySelector(".anchor-strip");
    if (!strip || !("IntersectionObserver" in window)) return;
    var links = {};
    var sections = [];
    strip.querySelectorAll('a[href^="#"]').forEach(function (a) {
      var id = a.getAttribute("href").slice(1);
      var section = document.getElementById(id);
      if (section) {
        links[id] = a;
        sections.push(section);
      }
    });
    if (!sections.length) return;
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          Object.keys(links).forEach(function (id) {
            links[id].classList.toggle("is-active", id === entry.target.id);
          });
        });
      },
      { rootMargin: "-30% 0px -60% 0px", threshold: 0 }
    );
    sections.forEach(function (s) {
      observer.observe(s);
    });
  }

  // Deep link: open and scroll to the control named in the URL fragment.
  function openFromHash() {
    if (!location.hash) return;
    var control = document.getElementById("c-" + location.hash.slice(1));
    if (control && control.classList.contains("control--expandable")) {
      setOpen(control, true);
      control.scrollIntoView({ block: "start" });
    }
  }
  // "Measuring…" screen (§ 8.1): run the live scan, then go to the report. Kept
  // here rather than inline because the production CSP is script-src 'self'.
  function initScan() {
    var box = document.querySelector(".scanning__inner[data-scan-url]");
    if (!box) return;
    var fallback = box.getAttribute("data-scan-fallback");
    function go(target) {
      location.replace(target || fallback);
    }
    fetch(box.getAttribute("data-scan-url"), { headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        go(data && data.redirect);
      })
      .catch(function () {
        go(fallback);
      });
  }

  function init() {
    openFromHash();
    initScrollSpy();
    initScan();
  }
  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", init);
})();
