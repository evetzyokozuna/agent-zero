import { createStore } from "/js/AlpineStore.js";
import { store as navStore } from "/components/chat/navigation/chat-navigation-store.js";
import * as api from "/js/api.js";
import {
  toastFrontendInfo,
  NotificationPriority,
} from "/components/notifications/notification-store.js";
import { sleep } from "/js/sleep.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";

const model = {
  // items: [],
  get items() {
    return chatsStore.selectedContext?.message_queue || [];
  },

  pendingItems: [], // Local pending items (uploading to queue)

  _pendingAddOps: {},

  _lastAddToQueuePromise: Promise.resolve(),
  _epoch: 0,

  bumpEpoch() {
    this._epoch = (Number(this._epoch) || 0) + 1;
    this._cancelPendingAddOps();
    return this._epoch;
  },

  getEpoch() {
    return Number(this._epoch) || 0;
  },

  setEpoch(epoch) {
    const parsed = Number(epoch);
    if (Number.isFinite(parsed) && parsed >= 0) {
      this._epoch = Math.floor(parsed);
    }
    return this._epoch;
  },

  _applyServerEpoch(payload) {
    if (!payload || typeof payload !== "object") return;
    if (Object.prototype.hasOwnProperty.call(payload, "epoch")) {
      this.setEpoch(payload.epoch);
    }
  },

  async syncEpochForContext(context) {
    if (!context) return this.getEpoch();
    try {
      const response = await api.callJsonApi("/pause", {
        paused: false,
        context,
      });
      this._applyServerEpoch(response);
    } catch (_e) {
      // no-op
    }
    return this.getEpoch();
  },

  _cancelPendingAddOps() {
    const pending = this._pendingAddOps || {};
    for (const op of Object.values(pending)) {
      if (!op) continue;
      op.canceled = true;
      if (op.controller) {
        try {
          op.controller.abort();
        } catch (_e) {
          // no-op
        }
      }
    }
    this._pendingAddOps = {};
    this.pendingItems = [];
    // Break the sequencing chain so stale operations cannot enqueue later.
    this._lastAddToQueuePromise = Promise.resolve();
  },

  _getQueueScrollerEl() {
    return document.querySelector(".queue-preview .queue-items");
  },

  scrollQueueToBottom() {
    const el = this._getQueueScrollerEl();
    if (!el) return;

    const scroll = () => {
      el.scrollTop = el.scrollHeight;
    };

    requestAnimationFrame(() => {
      scroll();
      requestAnimationFrame(scroll);
    });
  },

  get hasQueue() {
    return this.items.length > 0 || this.pendingItems.length > 0;
  },

  get count() {
    return this.items.length + this.pendingItems.length;
  },

  // Combined items for display: confirmed first, then pending at the end
  get allItems() {
    return [...this.items, ...this.pendingItems];
  },

  async addToQueue(text, attachments = []) {
    const context = globalThis.getContext?.();
    if (!context) return false;
    const opEpoch = Number(this._epoch) || 0;

    // Generate a temporary ID for pending item
    const tempId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const pendingItem = {
      id: tempId,
      text: text.substring(0, 200) || "(attachment only)",
      attachments: attachments.map((a) => a.name || a.file?.name || "file"),
      pending: true,
    };

    const controller =
      typeof AbortController !== "undefined" ? new AbortController() : null;
    this._pendingAddOps = {
      ...this._pendingAddOps,
      [tempId]: {
        canceled: false,
        controller,
      },
    };

    // Add to pending immediately for UI feedback
    this.pendingItems = [...this.pendingItems, pendingItem];
    this.scrollQueueToBottom();

    const run = async () => {
      if ((Number(this._epoch) || 0) !== opEpoch) {
        return false;
      }
      const op = this._pendingAddOps?.[tempId];
      if (!op || op.canceled) {
        this._pendingAddOps = { ...this._pendingAddOps };
        delete this._pendingAddOps[tempId];
        return false;
      }

      try {
        let filenames = [];
        if (attachments.length > 0) {
          const formData = new FormData();
          for (const att of attachments) {
            formData.append("file", att.file || att);
          }
          const resp = await api.fetchApi("/upload", {
            method: "POST",
            body: formData,
            signal: op.controller ? op.controller.signal : undefined,
          });
          if (resp.ok) {
            const result = await resp.json();
            filenames = result.filenames || [];
          }
        }

        const resp = await api.fetchApi("/message_queue_add", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "same-origin",
          body: JSON.stringify({
            context,
            epoch: this.getEpoch(),
            text,
            attachments: filenames,
            item_id: tempId,
          }),
          signal: op.controller ? op.controller.signal : undefined,
        });

        if (!resp || !resp.ok) {
          try {
            const errJson = await resp.json();
            this._applyServerEpoch(errJson);
          } catch (_e) {
            // no-op
          }
          return false;
        }
        if ((Number(this._epoch) || 0) !== opEpoch) {
          return false;
        }

        const response = await resp.json();
        this._applyServerEpoch(response);

        return response?.ok || false;
      } catch (e) {
        if (e?.name !== "AbortError") {
          console.error("Failed to queue message:", e);
        }
        return false;
      } finally {
        this._pendingAddOps = { ...this._pendingAddOps };
        delete this._pendingAddOps[tempId];
      }
    };

    // Chain promises to ensure sequential execution
    const previous = this._lastAddToQueuePromise || Promise.resolve();
    const chained = previous.catch(() => false).then(run);
    this._lastAddToQueuePromise = chained.catch(() => false);
    return await chained;
  },

  async removeItem(itemId) {
    const context = globalThis.getContext?.();
    if (!context) return;

    const isPending = this.pendingItems.some((p) => p.id === itemId);
    if (isPending) {
      const op = this._pendingAddOps?.[itemId];
      if (op) {
        op.canceled = true;
        if (op.controller) {
          op.controller.abort();
        }
      }
      this.pendingItems = this.pendingItems.filter((p) => p.id !== itemId);
      return;
    }

    try {
      const response = await api.callJsonApi("/message_queue_remove", {
        context,
        epoch: this.getEpoch(),
        item_id: itemId,
      });
      this._applyServerEpoch(response);
    } catch (e) {
      console.error("Failed to remove from queue:", e);
    }
  },

  async clearQueue(options = {}) {
    const hard = Boolean(options?.hard);
    if (hard) {
      this._cancelPendingAddOps();
    }
    const context = globalThis.getContext?.();
    if (!context) return;
    try {
      const response = await api.callJsonApi("/message_queue_remove", {
        context,
        epoch: this.getEpoch(),
      });
      this._applyServerEpoch(response);
    } catch (e) {
      console.error("Failed to clear queue:", e);
    }
  },

  async sendItem(itemId) {
    const context = globalThis.getContext?.();
    if (!context) return;
    try {
      const response = await api.callJsonApi("/message_queue_send", {
        context,
        epoch: this.getEpoch(),
        item_id: itemId,
      });
      this._applyServerEpoch(response);
    } catch (e) {
      console.error("Failed to send queued message:", e);
    }
  },

  async sendAll() {
    const context = globalThis.getContext?.();
    if (!context || !this.hasQueue) return;

    // check for pending uploads and notify user
    if (this.pendingItems.length > 0) {
      await sleep(1000);
      if (this.pendingItems.length > 0) {
        toastFrontendInfo(
          "There are pending uploads in the queue. You can wait for them to finish or remove them.",
          "Pending uploads",
          3,
          "pending-uploads",
          NotificationPriority.NORMAL,
          true,
        );
        return;
      }
    }

    if (!this.hasQueue) return;
    try {
      navStore.scrollToBottom();
      const response = await api.callJsonApi("/message_queue_send", {
        context,
        epoch: this.getEpoch(),
        send_all: true,
      });
      this._applyServerEpoch(response);
    } catch (e) {
      console.error("Failed to send all queued:", e);
    }
  },

  updateFromPoll() {
    // this.items = queue || [];

    if (this.pendingItems.length > 0) {
      const serverIds = new Set(this.items.map((i) => i.id).filter(Boolean));
      this.pendingItems = this.pendingItems.filter((p) => {
        if (!p.id) return true;
        return !serverIds.has(p.id);
      });
    }
    // this.scrollQueueToBottom();
  },

  getAttachmentUrl(filename) {
    return `/image_get?path=/a0/usr/uploads/${encodeURIComponent(filename)}`;
  },
};

const store = createStore("messageQueue", model);
export { store };
