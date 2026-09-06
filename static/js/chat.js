/* FINTECPESSOAL — Assistente Fintec (MÓDULO CHAT).
   Interface conversacional de lançamentos por linguagem natural.
   A interpretação é 100% backend (determinística, sem IA externa); aqui fica
   apenas a UX: envio, typing indicator (atraso só no frontend), rascunho
   editável e confirmação. Nada é salvo antes de "Confirmar lançamento". */
(function () {
  "use strict";

  var TYPING_MS = 450;
  var KIND_ACTIVE = {
    income: [
      "border-success-500",
      "bg-success-500/10",
      "text-success-400",
      "ring-2",
      "ring-success-500/20",
    ],
    expense: [
      "border-danger-500",
      "bg-danger-500/10",
      "text-danger-400",
      "ring-2",
      "ring-danger-500/20",
    ],
  };
  var KIND_TONE = { income: "success", expense: "danger" };

  var els = {};
  var state = {
    awaiting: false,
    draft: null,
    currentMessage: null,
    kind: null,
    accounts: [],
    cards: [],
    categories: [],
  };

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  function $id(id) { return document.getElementById(id); }

  function cacheEls() {
    if (els.ready) return;
    els.modal = $id("chat-modal");
    els.backdrop = $id("chat-backdrop");
    els.messages = $id("chat-messages");
    els.input = $id("chat-input");
    els.send = $id("chat-send");
    els.card = $id("chat-draft-card");
    els.value = $id("draft-value");
    els.date = $id("draft-date");
    els.desc = $id("draft-desc");
    els.category = $id("draft-category");
    els.account = $id("draft-account");
    els.acctRow = $id("draft-account-row");
    els.cardSel = $id("draft-card");
    els.cardRow = $id("draft-card-row");
    els.error = $id("draft-error");
    els.confirm = $id("draft-confirm");
    els.edit = $id("draft-edit");
    els.cancel = $id("draft-cancel");
    els.greeting = $id("chat-greeting-tpl");
    els.kindBadge = $id("draft-kind-badge");
    els.kindBtns = els.modal ? els.modal.querySelectorAll("[data-draft-kind]") : [];
    els.chips = els.modal ? els.modal.querySelectorAll("[data-chat-example]") : [];
    els.ready = true;
  }

  function csrfToken() {
    try {
      var m = document.cookie.match(/(^|; )csrftoken=([^;]*)/);
      return m ? decodeURIComponent(m[2]) : "";
    } catch (e) { return ""; }
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      credentials: "same-origin",
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  // ------------------------------------------------------------------ abas
  function scrollBottom() {
    if (els.messages) els.messages.scrollTop = els.messages.scrollHeight;
  }

  function assistantBubble(text, isTyping) {
    var row = document.createElement("div");
    row.className = "flex items-start gap-2.5";
    var avatar = document.createElement("span");
    avatar.className =
      "mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-accent text-white shadow-soft";
    avatar.setAttribute("aria-hidden", "true");
    avatar.innerHTML =
      '<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.8 4.6L18.5 9.5l-4.7 1.9L12 16l-1.8-4.6-4.7-1.9 4.7-1.9Z"/></svg>';
    var col = document.createElement("div");
    col.className = "max-w-[82%]";
    var bubble = document.createElement("div");
    bubble.className =
      "rounded-2xl rounded-tl-md border border-border bg-card px-4 py-3 text-sm leading-relaxed text-foreground shadow-soft";
    if (isTyping) {
      bubble.setAttribute("role", "status");
      bubble.setAttribute("aria-live", "polite");
      bubble.innerHTML =
        '<span class="sr-only">Fintec está analisando</span>' +
        '<span class="chat-typing flex items-center gap-2.5" aria-hidden="true">' +
        '<span class="text-muted-foreground">Fintec analisando</span>' +
        '<span class="flex items-center gap-1">' +
        '<span class="typing-dot h-1.5 w-1.5 rounded-full bg-brand-400 animate-bounce" style="animation-delay:0ms"></span>' +
        '<span class="typing-dot h-1.5 w-1.5 rounded-full bg-brand-400 animate-bounce" style="animation-delay:150ms"></span>' +
        '<span class="typing-dot h-1.5 w-1.5 rounded-full bg-brand-400 animate-bounce" style="animation-delay:300ms"></span>' +
        "</span></span>";
      bubble.classList.remove(
        "rounded-tl-md", "bg-card", "border", "border-border", "shadow-soft"
      );
      bubble.classList.add("rounded-full", "bg-muted/70");
    } else {
      bubble.textContent = text;
    }
    col.appendChild(bubble);
    row.appendChild(avatar);
    row.appendChild(col);
    return row;
  }

  function userBubble(text) {
    var row = document.createElement("div");
    row.className = "flex justify-end";
    var bubble = document.createElement("div");
    bubble.className =
      "max-w-[82%] rounded-2xl rounded-tr-md bg-gradient-to-br from-brand-500 to-accent px-4 py-2.5 text-sm font-medium text-white shadow-soft";
    bubble.textContent = text;
    row.appendChild(bubble);
    return row;
  }

  function addAssistant(text) {
    els.messages.appendChild(assistantBubble(text, false));
    scrollBottom();
  }

  function addUser(text) {
    els.messages.appendChild(userBubble(text));
    scrollBottom();
  }

  function addTyping() {
    var el = assistantBubble("", true);
    els.messages.appendChild(el);
    scrollBottom();
    return {
      remove: function () { if (el.parentNode) el.parentNode.removeChild(el); },
    };
  }

  // --------------------------------------------------------------- rascunho
  function formatBrl(value) {
    if (value == null || value === "") return "";
    var s = String(value).trim();
    if (s.indexOf(".") !== -1) {
      var parts = s.split(".");
      return parts[0] + "," + (parts[1] ? parts[1] : "00");
    }
    return s;
  }

  function fillSelect(select, items, placeholder) {
    select.innerHTML = "";
    if (placeholder) {
      var ph = document.createElement("option");
      ph.value = "";
      ph.textContent = placeholder;
      select.appendChild(ph);
    }
    items.forEach(function (item) {
      var o = document.createElement("option");
      o.value = String(item.id);
      o.textContent = item.name;
      select.appendChild(o);
    });
  }

  function showError(msg) {
    els.error.textContent = msg;
    els.error.classList.remove("hidden");
  }

  function clearError() {
    els.error.classList.add("hidden");
    els.error.textContent = "";
  }

  function setKind(kind) {
    state.kind = kind;
    var tone = KIND_TONE[kind] || "";
    els.kindBtns.forEach(function (btn) {
      btn.classList.remove("text-muted-foreground");
      ["border-success-500", "bg-success-500/10", "text-success-400", "ring-2", "ring-success-500/20",
       "border-danger-500", "bg-danger-500/10", "text-danger-400", "ring-2", "ring-danger-500/20"].forEach(
        function (c) { btn.classList.remove(c); }
      );
      if (btn.getAttribute("data-draft-kind") === kind) {
        KIND_ACTIVE[kind].forEach(function (c) { btn.classList.add(c); });
        btn.setAttribute("aria-pressed", "true");
      } else {
        btn.classList.add("text-muted-foreground");
        btn.setAttribute("aria-pressed", "false");
      }
    });

    if (els.kindBadge) {
      if (kind === "income") {
        els.kindBadge.textContent = "Entrada";
        els.kindBadge.className =
          "ml-auto hidden rounded-md bg-success-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-success-400";
        els.kindBadge.classList.remove("hidden");
      } else if (kind === "expense") {
        els.kindBadge.textContent = "Saída";
        els.kindBadge.className =
          "ml-auto hidden rounded-md bg-danger-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-danger-400";
        els.kindBadge.classList.remove("hidden");
      } else {
        els.kindBadge.classList.add("hidden");
      }
    }

    if (kind === "income") {
      els.acctRow.classList.remove("hidden");
      els.cardRow.classList.add("hidden");
      els.cardSel.value = "";
    } else if (kind === "expense") {
      els.acctRow.classList.remove("hidden");
      els.cardRow.classList.remove("hidden");
    }
    fillCategoryOptions();
  }

  function fillCategoryOptions() {
    var list = (state.categories || []).filter(function (c) {
      return state.kind ? c.kind === state.kind : true;
    });
    fillSelect(els.category, list, "Sem categoria (opcional)");
    if (state.draft && state.draft.category_id) {
      var found = list.some(function (c) { return String(c.id) === String(state.draft.category_id); });
      if (found) els.category.value = String(state.draft.category_id);
    }
  }

  function renderDraft(data) {
    var d = data.draft;
    state.draft = d;
    state.accounts = data.accounts || [];
    state.cards = data.cards || [];
    state.categories = data.categories || [];

    els.value.value = formatBrl(d.amount);
    els.date.value = d.date || "";
    els.desc.value = d.description || "";

    fillSelect(els.account, state.accounts, d.type === "income"
      ? "Selecione a conta de destino"
      : "Selecione a conta de origem");
    fillSelect(els.cardSel, state.cards, "Selecione o cartão");

    if (d.type) {
      setKind(d.type);
    } else {
      state.kind = null;
      els.kindBtns.forEach(function (btn) {
        btn.classList.remove(
          "border-success-500", "bg-success-500/10", "text-success-400",
          "border-danger-500", "bg-danger-500/10", "text-danger-400",
          "ring-2", "ring-success-500/20", "ring-danger-500/20"
        );
        btn.classList.add("text-muted-foreground");
        btn.setAttribute("aria-pressed", "false");
      });
      if (els.kindBadge) els.kindBadge.classList.add("hidden");
      els.acctRow.classList.remove("hidden");
      els.cardRow.classList.add("hidden");
      fillCategoryOptions();
    }

    clearError();
    els.card.classList.remove("hidden");
    els.value.focus();
    var end = els.value.value.length;
    if (end && els.value.setSelectionRange) els.value.setSelectionRange(0, end);
    scrollBottom();
  }

  function hideDraft() {
    if (!els.card) return;
    els.card.classList.add("hidden");
    els.error.classList.add("hidden");
    if (els.kindBadge) els.kindBadge.classList.add("hidden");
    state.draft = null;
    state.kind = null;
  }

  // ---------------------------------------------------------------- envio
  function setAwaiting(on) {
    state.awaiting = on;
    els.input.disabled = on;
    els.send.disabled = on;
    if (els.send) els.send.classList.toggle("chat-send-busy", on);
    els.chips.forEach(function (chip) { chip.disabled = on; });
  }

  function sendMessage() {
    if (state.awaiting || !els.input) return;
    var text = els.input.value.trim();
    if (!text) { els.input.focus(); return; }

    hideDraft();
    addUser(text);
    setAwaiting(true);
    var typing = addTyping();

    setTimeout(function () {
      post(els.modal.getAttribute("data-parse-url"), { message: text })
        .then(function (data) {
          typing.remove();
          state.currentMessage = text;
          if (data && data.success) {
            addAssistant(data.message || "Interpretei sua mensagem.");
            renderDraft(data);
          } else {
            addAssistant((data && data.message) || "Não consegui interpretar. Tente de novo.");
          }
          setAwaiting(false);
        })
        .catch(function () {
          typing.remove();
          addAssistant("Ops, não consegui me conectar. Tente de novo.");
          setAwaiting(false);
        });
    }, TYPING_MS);
  }

  function confirmDraft(event) {
    if (event) event.preventDefault();
    if (state.awaiting) return;

    if (!state.kind) {
      showError("Escolha se foi uma Entrada (receita) ou uma Saída (despesa).");
      return;
    }
    var accountId = els.account.value;
    var cardId = state.kind === "expense" ? els.cardSel.value : "";
    if (state.kind === "income" && !accountId) {
      showError("Selecione a conta de destino da receita.");
      return;
    }
    if (state.kind === "expense" && !accountId && !cardId) {
      showError("Selecione uma conta (ou cartão) para o lançamento.");
      return;
    }

    clearError();
    setAwaiting(true);
    els.confirm.disabled = true;
    els.edit.disabled = true;
    els.cancel.disabled = true;
    var label = els.confirm.querySelector(".draft-confirm-label");
    if (label) label.textContent = "Salvando…";

    var payload = {
      message: state.currentMessage,
      kind: state.kind,
      account_id: accountId ? Number(accountId) : null,
      card_id: cardId ? Number(cardId) : null,
      category_id: els.category.value ? Number(els.category.value) : null,
      date: els.date.value,
      amount: els.value.value,
      description: els.desc.value,
    };

    post(els.modal.getAttribute("data-confirm-url"), payload)
      .then(function (data) {
        setAwaiting(false);
        els.confirm.disabled = false;
        els.edit.disabled = false;
        els.cancel.disabled = false;
        if (label) label.textContent = "Confirmar lançamento";
        if (data && data.success) {
          addAssistant(data.message || "Lançamento registrado!");
          hideDraft();
          els.input.value = "";
          els.input.focus();
        } else {
          showError((data && data.message) || "Não foi possível registrar o lançamento.");
        }
      })
      .catch(function () {
        setAwaiting(false);
        els.confirm.disabled = false;
        els.edit.disabled = false;
        els.cancel.disabled = false;
        if (label) label.textContent = "Confirmar lançamento";
        showError("Ops, não consegui me conectar. Tente de novo.");
      });
  }

  // ------------------------------------------------------------- abertura
  function openChat() {
    cacheEls();
    els.modal.classList.remove("hidden");
    els.backdrop.classList.remove("hidden");
    document.body.classList.add("overflow-hidden");
    resetConversation();
  }

  function closeChat() {
    if (!els.modal) return;
    hideDraft();
    els.modal.classList.add("hidden");
    els.backdrop.classList.add("hidden");
    document.body.classList.remove("overflow-hidden");
    var trigger = document.querySelector("[data-chat-open]:not([hidden])");
    if (trigger) trigger.focus();
  }

  function resetConversation() {
    els.messages.innerHTML = "";
    if (els.greeting && els.greeting.content) {
      els.messages.appendChild(els.greeting.content.cloneNode(true));
    }
    hideDraft();
    state.currentMessage = null;
    state.accounts = [];
    state.cards = [];
    state.categories = [];
    els.input.value = "";
    setAwaiting(false);
    scrollBottom();
    els.input.focus();
  }

  // ------------------------------------------------- menus CTA / FAB mobile
  function closeMenus() {
    var ctaMenu = $id("cta-menu");
    var fabMenu = document.querySelector("[data-fab-menu]");
    if (ctaMenu) ctaMenu.classList.add("hidden");
    if (fabMenu) fabMenu.classList.add("hidden");
    ["data-cta-toggle", "data-fab-toggle"].forEach(function (attr) {
      document.querySelectorAll("[" + attr + "]").forEach(function (b) {
        b.setAttribute("aria-expanded", "false");
      });
    });
  }

  function documentClick(e) {
    cacheEls();

    if (e.target.closest("[data-chat-open]")) {
      closeMenus();
      openChat();
      return;
    }
    if (e.target.closest("[data-close-chat]")) {
      closeChat();
      return;
    }
    if (e.target === els.backdrop) {
      closeChat();
      return;
    }

    var toggle = e.target.closest("[data-cta-toggle], [data-fab-toggle]");
    if (toggle) {
      e.preventDefault();
      var menu = toggle.hasAttribute("data-cta-toggle")
        ? $id("cta-menu")
        : document.querySelector("[data-fab-menu]");
      var willOpen = menu && menu.classList.contains("hidden");
      closeMenus();
      if (willOpen) {
        menu.classList.remove("hidden");
        toggle.setAttribute("aria-expanded", "true");
      }
      return;
    }

    var inMenu =
      e.target.closest("#cta-menu") ||
      e.target.closest("[data-fab-menu]");
    if (!inMenu) closeMenus();
  }

  // ------------------------------------------------------------- init
  onReady(function () {
    cacheEls();
    if (!els.modal) return;

    document.addEventListener("click", documentClick, true);

    els.send.addEventListener("click", sendMessage);
    els.input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    els.confirm.addEventListener("click", confirmDraft);
    els.card.addEventListener("submit", confirmDraft);

    els.chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        els.input.value = chip.getAttribute("data-chat-example") || "";
        els.input.focus();
        sendMessage();
      });
    });

    els.edit.addEventListener("click", function () {
      els.value.focus();
      if (els.value.setSelectionRange) {
        els.value.setSelectionRange(0, els.value.value.length);
      }
    });

    els.cancel.addEventListener("click", function () {
      addAssistant(
        state.kind === "income"
          ? "Tudo bem, descartei o rascunho. Posso ajudar com outro lançamento?"
          : "Tudo bem, descartei a despesa. Posso ajudar com outro lançamento?"
      );
      hideDraft();
      els.input.value = "";
      setAwaiting(false);
      els.input.focus();
    });

    els.kindBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        setKind(btn.getAttribute("data-draft-kind"));
        clearError();
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        var modalHidden = els.modal.classList.contains("hidden");
        if (!modalHidden) {
          e.preventDefault();
          closeChat();
        } else {
          closeMenus();
        }
      }
    });
  });
})();