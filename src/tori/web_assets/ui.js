"use strict";

(function initializeToriUI() {
  const csrfToken = document.querySelector('meta[name="tori-csrf"]').content;
  const validViews = new Set([
    "home", "conversation", "projects", "security", "tasks", "scheduled-work", "memories", "knowledge", "commands", "skills-mcp", "settings",
  ]);
  const managementViews = new Set([
    "projects", "tasks", "scheduled-work", "memories", "knowledge",
  ]);
  const panels = Array.from(document.querySelectorAll("[data-view-panel]"));
  const links = Array.from(document.querySelectorAll("[data-view-link]"));
  const primaryNavigation = document.querySelector(".primary-nav");
  const sidebar = document.querySelector(".sidebar");
  const localBoundary = document.querySelector(".local-boundary");
  const mobileMenu = document.getElementById("mobile-menu-panel");
  const mobileNavTrigger = document.querySelector(".mobile-nav-trigger");
  const mobileNavClose = document.querySelector(".mobile-panel-close");
  const mobileNavigationSlot = document.getElementById("mobile-navigation-slot");
  const mobileHistorySlot = document.getElementById("mobile-history-slot");
  const mobileUtilityPanel = document.getElementById("mobile-utility-panel");
  const mobileUtilitySlot = document.getElementById("mobile-utility-slot");
  const mobileUtilityToggle = document.querySelector("[data-utility-toggle]");
  const mobileUtilityClose = document.querySelector(".mobile-utility-close");
  const utilityRail = document.getElementById("utility-rail");
  const utilityModule = utilityRail.querySelector("[data-utility-module-root]");
  const sidebarConversations = document.querySelector(".sidebar-conversations");
  const homeOverview = document.getElementById("home-overview-slot");
  const homeSession = document.getElementById("home-session-slot");
  const homeHeroSession = document.getElementById("home-hero-session");
  const sessionCard = document.getElementById("utility-status-card");
  const homeWorkStack = document.getElementById("home-work-stack");
  const homeSupportStack = document.getElementById("home-support-stack");
  const overviewCards = [
    "utility-status-card", "utility-host-card", "utility-attention-card",
    "utility-coding-work-card", "utility-research-card", "utility-upcoming-card",
    "utility-activity-card",
  ].map(id => document.getElementById(id));
  const [, hostCard, attentionCard, codingCard, researchCard, upcomingCard, activityCard] = overviewCards;
  const conversationPanel = document.getElementById("view-conversation");
  const modelControls = document.getElementById("session-model-controls");
  const projectIndicator = document.getElementById("active-project");
  const feedback = document.querySelector(".feedback-stack");
  const narrowLayout = window.matchMedia("(max-width: 1023px)");
  let activeView = null;
  let dialogReturnFocus = null;

  function viewFromLocation() {
    if (window.location.pathname === "/") {
      return window.location.hash === "#home" ? "home" : "conversation";
    }
    if (window.location.pathname === "/manage") {
      const candidate = window.location.hash.slice(1);
      return managementViews.has(candidate) ? candidate : "memories";
    }
    if (window.location.pathname === "/commands") {
      return "commands";
    }
    if (window.location.pathname === "/settings") {
      return "settings";
    }
    if (window.location.pathname === "/security") return "security";
    const initial = document.body.dataset.initialView;
    return validViews.has(initial) ? initial : "conversation";
  }

  function destinationFor(view) {
    if (view === "home") return "/#home";
    if (view === "conversation") {
      return "/";
    }
    if (view === "security") return "/security";
    if (view === "commands" || view === "settings" || view === "skills-mcp") {
      return view === "skills-mcp" ? "/skills" : `/${view}`;
    }
    return `/manage#${view}`;
  }

  function applyView(view, {focus = false} = {}) {
    const selected = validViews.has(view) ? view : "conversation";
    activeView = selected;
    document.body.dataset.activeView = selected;
    syncResponsiveControls();
    for (const panel of panels) {
      const visible = panel.dataset.viewPanel === selected;
      panel.hidden = !visible;
    }
    for (const link of links) {
      if (link.dataset.viewLink === selected) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    }
    window.ToriViewModules.activate(selected);
    const heading = document.querySelector(
      `[data-view-panel="${selected}"] h1`
    );
    document.title = heading ? `Tori — ${heading.textContent}` : "Tori";
    if (focus && heading) {
      heading.setAttribute("tabindex", "-1");
      heading.focus({preventScroll: true});
    }
    document.dispatchEvent(new CustomEvent("tori:viewchange", {
      detail: {view: selected},
    }));
    closeMobilePanels();
  }

  function setPanelOpen(panel, trigger, open) {
    panel.hidden = !open;
    if (trigger) trigger.setAttribute("aria-expanded", String(open));
  }

  function closeMobilePanels() {
    setPanelOpen(mobileMenu, mobileNavTrigger, false);
    setPanelOpen(mobileUtilityPanel, mobileUtilityToggle, false);
  }

  function syncResponsiveControls() {
    if (homeOverview && activeView === "home") {
      homeOverview.append(utilityModule);
      homeHeroSession.append(sessionCard);
      homeSession.append(modelControls, projectIndicator);
      homeWorkStack.append(codingCard, researchCard, activityCard);
      homeSupportStack.append(hostCard, attentionCard, upcomingCard);
    } else if (homeOverview) {
      utilityModule.append(...overviewCards);
      conversationPanel.insertBefore(modelControls, feedback);
      conversationPanel.insertBefore(projectIndicator, feedback);
    }
    if (narrowLayout.matches) {
      mobileNavigationSlot.append(primaryNavigation);
      mobileHistorySlot.append(sidebarConversations);
      if (activeView !== "home") mobileUtilitySlot.append(utilityModule);
    } else {
      sidebar.insertBefore(primaryNavigation, localBoundary);
      sidebar.insertBefore(sidebarConversations, localBoundary);
      if (activeView !== "home") utilityRail.append(utilityModule);
      closeMobilePanels();
    }
  }

  function navigate(view, {replace = false, focus = true} = {}) {
    const selected = validViews.has(view) ? view : "conversation";
    const method = replace ? "replaceState" : "pushState";
    window.history[method]({toriView: selected}, "", destinationFor(selected));
    applyView(selected, {focus});
  }

  for (const link of links) {
    link.addEventListener("click", (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey ||
          event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin) {
        return;
      }
      event.preventDefault();
      navigate(link.dataset.viewLink);
    });
  }
  mobileNavTrigger.addEventListener("click", () => {
    const opening = mobileMenu.hidden;
    closeMobilePanels();
    setPanelOpen(mobileMenu, mobileNavTrigger, opening);
  });
  mobileNavClose.addEventListener("click", closeMobilePanels);
  mobileUtilityToggle.addEventListener("click", () => {
    const opening = mobileUtilityPanel.hidden;
    closeMobilePanels();
    setPanelOpen(mobileUtilityPanel, mobileUtilityToggle, opening);
  });
  mobileUtilityClose.addEventListener("click", closeMobilePanels);
  for (const shortcut of document.querySelectorAll("[data-settings-shortcut]")) {
    shortcut.addEventListener("click", () => navigate("settings"));
  }

  window.addEventListener("popstate", () => applyView(viewFromLocation(), {focus: true}));
  window.addEventListener("hashchange", () => applyView(viewFromLocation(), {focus: true}));
  if (typeof narrowLayout.addEventListener === "function") {
    narrowLayout.addEventListener("change", syncResponsiveControls);
  } else {
    narrowLayout.addListener(syncResponsiveControls);
  }

  async function requestJson(path, {method = "GET", body} = {}) {
    const options = {
      method,
      cache: "no-store",
      credentials: "same-origin",
      headers: {},
    };
    if (method === "POST") {
      options.headers = {
        "Content-Type": "application/json",
        "X-Tori-CSRF": csrfToken,
      };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    const documentBody = await response.json();
    if (!response.ok) {
      const error = new Error(documentBody.error || "The local request failed.");
      error.code = documentBody.code || "request_failed";
      error.document = documentBody;
      throw error;
    }
    return documentBody;
  }

  function showError(element, message) {
    element.textContent = message;
    element.hidden = !message;
  }

  function setStatus(element, message, state = "neutral") {
    element.textContent = message;
    element.dataset.state = state;
    if (element.id === "status") {
      window.ToriUtilityRail?.setApplicationStatus(message, state);
    }
  }

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    if (text !== undefined) {
      element.textContent = String(text);
    }
    return element;
  }

  function setBusy(element, busy) {
    element.setAttribute("aria-busy", String(Boolean(busy)));
  }

  function openDialog(dialog, {returnFocus, initialFocus} = {}) {
    dialogReturnFocus = returnFocus || document.activeElement;
    dialog.showModal();
    if (initialFocus) {
      initialFocus.focus();
    }
  }

  function closeDialog(dialog) {
    if (dialog.open) {
      dialog.close();
    }
    const target = dialogReturnFocus;
    dialogReturnFocus = null;
    if (target && target.isConnected && typeof target.focus === "function") {
      target.focus();
    }
  }

  window.ToriUI = Object.freeze({
    applyView,
    closeDialog,
    createElement,
    currentView: () => activeView,
    csrfToken,
    navigate,
    openDialog,
    requestJson,
    setBusy,
    setStatus,
    showError,
  });

  syncResponsiveControls();
  applyView(viewFromLocation());
}());
