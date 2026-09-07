/* FINTECPESSOAL — Leitura em voz alta do relatório IA (Web Speech API).
   Roda 100% no navegador, sem custo: usa as vozes nativas do sistema/browser.
   Preferência: voz pt-BR, priorizando variantes naturais/online quando existem. */
(function () {
  "use strict";

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  onReady(function () {
    var listenBtn = document.getElementById("btn-listen-report");
    var stopBtn = document.getElementById("btn-stop-report");
    var report = document.querySelector(".ai-report");
    if (!listenBtn || !report || !("speechSynthesis" in window)) {
      return;
    }

    var synth = window.speechSynthesis;
    var voices = [];
    var voice = null;
    var paused = false;

    function scoreVoice(v) {
      var name = (v.name || "") + " " + (v.lang || "");
      var s = 0;
      if (/pt[-_]?br/i.test(v.lang || "")) s += 10;
      else if (/^pt/i.test(v.lang || "")) s += 4;
      if (/natural|neural|online|premium|google|network/i.test(name)) s += 5;
      if (v.default) s += 1;
      return s;
    }

    function loadVoices() {
      voices = synth.getVoices() || [];
      if (!voices.length) return;
      voice = voices.slice().sort(function (a, b) {
        return scoreVoice(b) - scoreVoice(a);
      })[0];
    }

    if (typeof synth.onvoiceschanged !== "undefined") {
      synth.onvoiceschanged = loadVoices;
    }
    loadVoices();

    function reportText() {
      var t = report.textContent || "";
      return t.replace(/\s+/g, " ").trim();
    }

    function setLabel(text) {
      var label = listenBtn.querySelector("[data-listen-label]");
      if (label) label.textContent = text;
    }

    function setUI(state) {
      if (state === "idle") {
        setLabel("Ouvir");
        listenBtn.setAttribute("aria-pressed", "false");
        if (stopBtn) stopBtn.classList.add("hidden");
      } else if (state === "playing") {
        setLabel(paused ? "Continuar" : "Pausar");
        listenBtn.setAttribute("aria-pressed", "true");
        if (stopBtn) stopBtn.classList.remove("hidden");
      }
    }

    function speakReport() {
      var text = reportText();
      if (!text) return;
      synth.cancel();
      var u = new SpeechSynthesisUtterance(text);
      if (voice) {
        u.voice = voice;
        u.lang = voice.lang;
      } else {
        u.lang = "pt-BR";
      }
      u.rate = 1.0;
      u.onend = function () {
        paused = false;
        setUI("idle");
      };
      u.onerror = function (ev) {
        if (!ev || ev.error !== "canceled") {
          paused = false;
          setUI("idle");
        }
      };
      synth.speak(u);
      paused = false;
      setUI("playing");
    }

    function toggle() {
      if (synth.speaking && synth.paused) {
        synth.resume();
        paused = false;
        setUI("playing");
        return;
      }
      if (synth.speaking) {
        synth.pause();
        paused = true;
        setUI("playing");
        return;
      }
      speakReport();
    }

    function stop() {
      synth.cancel();
      paused = false;
      setUI("idle");
    }

    listenBtn.addEventListener("click", toggle);
    if (stopBtn) stopBtn.addEventListener("click", stop);
    window.addEventListener("beforeunload", stop);
  });
})();