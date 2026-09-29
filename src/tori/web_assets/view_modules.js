"use strict";

(function initializeViewModules() {
  const definitions = new Map();
  let active = null;

  function register(definition) {
    if (!definition || typeof definition.id !== "string" ||
        typeof definition.mount !== "function") {
      throw new TypeError("A view module requires an id and mount function.");
    }
    if (definitions.has(definition.id)) {
      throw new Error(`The ${definition.id} view module is already registered.`);
    }
    definitions.set(definition.id, Object.freeze({...definition}));
    if (document.body?.dataset?.activeView === definition.id) {
      activate(definition.id);
    }
  }

  function unmountActive() {
    if (!active) {
      return;
    }
    if (typeof active.lifecycle.unmount === "function") {
      active.lifecycle.unmount();
    }
    active = null;
  }

  function activate(id) {
    if (active?.id === id) {
      if (typeof active.lifecycle.refresh === "function") {
        active.lifecycle.refresh();
      }
      return;
    }
    unmountActive();
    const definition = definitions.get(id);
    if (!definition) {
      return;
    }
    const root = document.querySelector(`[data-view-module-root="${id}"]`);
    if (!root) {
      throw new Error(`The ${id} view module root is unavailable.`);
    }
    const lifecycle = definition.mount(root) || {};
    active = {id, lifecycle};
  }

  window.ToriViewModules = Object.freeze({activate, register});
}());
