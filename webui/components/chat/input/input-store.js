import { createStore } from "/js/AlpineStore.js";
import * as shortcuts from "/js/shortcuts.js";
import { websocket } from "/js/websocket.js";
import { store as fileBrowserStore } from "/components/modals/file-browser/file-browser-store.js";
import { store as messageQueueStore } from "/components/chat/message-queue/message-queue-store.js";
import { store as attachmentsStore } from "/components/chat/attachments/attachmentsStore.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";

const model = {
  paused: false,
  stopping: false,
  pendingFreshStart: false,
  stopEpoch: 0,
  message: "",

  _getSendState() {
    const hasInput = this.message.trim() || attachmentsStore?.attachments?.length > 0;
    const hasQueue = !!messageQueueStore?.hasQueue;
    const running = !!chatsStore.selectedContext?.running;

    if (hasQueue && !hasInput) return "all";
    if ((running || hasQueue) && hasInput) return "queue";
    return "normal";
  },

  get inputPlaceholder() {
    const state = this._getSendState();
    if (state === "all") return "Press Enter to send queued messages";
    return "Type your message here...";
  },

  // Computed: send button icon type
  get sendButtonIcon() {
    const state = this._getSendState();
    if (state === "all") return "send_and_archive";
    if (state === "queue") return "schedule_send";
    return "send";
  },

  // Computed: send button CSS class
  get sendButtonClass() {
    const state = this._getSendState();
    if (state === "all") return "send-queue send-all";
    if (state === "queue") return "send-queue queue";
    return "";
  },

  // Computed: send button title
  get sendButtonTitle() {
    const state = this._getSendState();
    if (state === "all") return "Send all queued messages";
    if (state === "queue") return "Add to queue";
    return "Send message";
  },

  init() {
    console.log("Input store initialized");
    // Event listeners are now handled via Alpine directives in the component
  },

  async sendMessage() {
    if (this.stopping) return;
    // After an explicit stop, request a fresh backend epoch before sending.
    if (this.pendingFreshStart) {
      try {
        const context = globalThis.getContext?.();
        if (globalThis.sendJsonData && context) {
          await globalThis.sendJsonData("/pause", {
            paused: false,
            context,
            ctxid: context,
            fresh_start: true,
            reset_monologue: true,
            stop_epoch: this.stopEpoch,
          });
        }
      } catch (_e) {
        // best effort; continue with send path
      } finally {
        this.paused = false;
        this.pendingFreshStart = false;
      }
    }
    // Delegate to the global function
    if (globalThis.sendMessage) {
      await globalThis.sendMessage();
    }
  },

  adjustTextareaHeight() {
    const chatInput = document.getElementById("chat-input");
    if (chatInput) {
      chatInput.style.height = "auto";
      chatInput.style.height = chatInput.scrollHeight + "px";
    }
  },

  async pauseAgent(paused) {
    const prev = this.paused;
    this.paused = paused;
    try {
      const context = globalThis.getContext?.();
      if (!globalThis.sendJsonData)
        throw new Error("sendJsonData not available");
      await globalThis.sendJsonData("/pause", { paused, context });
      if (!paused) {
        try {
          await websocket.connect();
        } catch (_e) {
          // no-op
        }
      }
    } catch (e) {
      this.paused = prev;
      if (globalThis.toastFetchError) {
        globalThis.toastFetchError("Error pausing agent", e);
      }
    }
  },

  async stopAgent() {
    if (this.stopping) return;
    const prevPaused = this.paused;
    this.stopping = true;
    this.paused = true;
    this.stopEpoch = (Number(this.stopEpoch) || 0) + 1;
    this.pendingFreshStart = true;

    const context = globalThis.getContext?.();
    const send = globalThis.sendJsonData;
    try {
      if (!send) throw new Error("sendJsonData not available");

      // Try explicit stop-like endpoints in order; backend capability differs by build.
      const payload = { context, ctxid: context, hard: true, stop: true };
      const stopEndpoints = ["/stop", "/interrupt", "/break", "/pause"];
      let stopped = false;
      for (const endpoint of stopEndpoints) {
        try {
          const body =
            endpoint === "/pause" ? { ...payload, paused: true } : payload;
          await send(endpoint, body);
          stopped = true;
          break;
        } catch (_e) {
          // try next endpoint
        }
      }
      if (!stopped) {
        throw new Error("No stop endpoint accepted request");
      }

      // Cut websocket stream immediately so current UI stops receiving loop updates.
      try {
        await websocket.disconnect();
      } catch (_e) {
        // no-op
      }

      // Clear any queued local draft state so no new work gets enqueued.
      if (messageQueueStore?.clearQueue) {
        try {
          if (messageQueueStore?.bumpEpoch) {
            messageQueueStore.bumpEpoch();
          }
          await messageQueueStore.clearQueue({ hard: true });
        } catch (_e) {
          // no-op; queue API varies across builds
        }
      }

      // Ensure UI no longer treats chat as running after explicit stop.
      if (chatsStore?.selectedContext) {
        chatsStore.selectedContext.running = false;
        chatsStore.selectedContext.message_queue = [];
      }
      this.message = "";
      this.adjustTextareaHeight();
    } catch (e) {
      this.paused = prevPaused;
      if (globalThis.toastFetchError) {
        globalThis.toastFetchError("Error stopping agent", e);
      }
    } finally {
      this.stopping = false;
    }
  },

  async nudge() {
    try {
      const context = await this._resolveContextIdForAction("nudge the agent");
      if (!context) return;
      await globalThis.sendJsonData("/nudge", { ctxid: context });
    } catch (e) {
      if (globalThis.toastFetchError) {
        globalThis.toastFetchError("Error nudging agent", e);
      }
    }
  },

  async loadKnowledge() {
    try {
      const ctxid = await this._resolveContextIdForAction("load knowledge");
      if (!ctxid) return;
      const resp = await shortcuts.callJsonApi("/knowledge_path_get", {
        ctxid,
      });
      if (!resp.ok) throw new Error("Error getting knowledge path");
      const path = resp.path;

      // open file browser and wait for it to close
      await fileBrowserStore.open(path);

      // progress notification
      shortcuts.frontendNotification({
        type: shortcuts.NotificationType.PROGRESS,
        message: "Loading knowledge...",
        priority: shortcuts.NotificationPriority.NORMAL,
        displayTime: 999,
        group: "knowledge_load",
        frontendOnly: true,
      });

      // then reindex knowledge
      await globalThis.sendJsonData("/knowledge_reindex", {
        ctxid,
      });

      // finished notification
      shortcuts.frontendNotification({
        type: shortcuts.NotificationType.SUCCESS,
        message: "Knowledge loaded successfully",
        priority: shortcuts.NotificationPriority.NORMAL,
        displayTime: 2,
        group: "knowledge_load",
        frontendOnly: true,
      });
    } catch (e) {
      // error notification
      shortcuts.frontendNotification({
        type: shortcuts.NotificationType.ERROR,
        message: "Error loading knowledge",
        priority: shortcuts.NotificationPriority.NORMAL,
        displayTime: 5,
        group: "knowledge_load",
        frontendOnly: true,
      });
    }
  },

  // previous implementation without projects
  async _loadKnowledge() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".txt,.pdf,.csv,.html,.json,.md";
    input.multiple = true;

    input.onchange = async () => {
      try {
        const ctxid = await this._resolveContextIdForAction("import knowledge");
        if (!ctxid) return;
        const formData = new FormData();
        for (let file of input.files) {
          formData.append("files[]", file);
        }

        formData.append("ctxid", ctxid);

        const response = await globalThis.fetchApi("/import_knowledge", {
          method: "POST",
          body: formData,
        });

        if (!response.ok) {
          if (globalThis.toast)
            globalThis.toast(await response.text(), "error");
        } else {
          const data = await response.json();
          if (globalThis.toast) {
            globalThis.toast(
              "Knowledge files imported: " + data.filenames.join(", "),
              "success"
            );
          }
        }
      } catch (e) {
        if (globalThis.toastFetchError) {
          globalThis.toastFetchError("Error loading knowledge", e);
        }
      }
    };

    input.click();
  },

  async _resolveContextIdForAction(actionLabel = "this action") {
    let ctxid = shortcuts.getCurrentContextId() || globalThis.getContext?.();
    if (ctxid) return ctxid;

    const contexts = Array.isArray(chatsStore.contexts)
      ? chatsStore.contexts.filter((ctx) => ctx && ctx.id)
      : [];
    if (contexts.length === 1) {
      const onlyContextId = contexts[0].id;
      try {
        await chatsStore.selectChat(onlyContextId);
      } catch (_e) {
        // best effort: continue with recovered id for this action
      }
      return onlyContextId;
    }

    if (globalThis.toast) {
      if (contexts.length > 1) {
        globalThis.toast(
          `Select a chat first to ${actionLabel}.`,
          "warning"
        );
      } else {
        globalThis.toast(
          `Create or select a chat first to ${actionLabel}.`,
          "warning"
        );
      }
    }
    return null;
  },

  async browseFiles(path) {
    if (!path) {
      try {
        const ctxid = shortcuts.getCurrentContextId() || globalThis.getContext?.();
        if (ctxid) {
          const resp = await shortcuts.callJsonApi("/chat_files_path_get", {
            ctxid,
          });
          if (resp.ok) path = resp.path;
        } else {
          // Dashboard file browsing should remain usable without chat selection.
          // Fall back to global workdir path instead of calling context-bound APIs with empty ctxid.
          const settingsResp = await shortcuts.callJsonApi("settings_get", null);
          path = settingsResp?.settings?.workdir_path || "/a0/usr/workdir";
          if (globalThis.toast) {
            globalThis.toast(
              "No chat selected. Opened default workspace files.",
              "info"
            );
          }
        }
      } catch (_e) {
        console.error("Error getting chat files path", _e);
      }
    }
    if (!path) return;
    await fileBrowserStore.open(path);
  },

  reset() {
    this.message = "";
    attachmentsStore.clearAttachments();
    this.adjustTextareaHeight();
  }
};

const store = createStore("chatInput", model);

export { store };
