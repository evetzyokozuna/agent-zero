import { createStore } from "/js/AlpineStore.js";
import * as API from "/js/api.js";
import { store as notificationStore } from "/components/notifications/notification-store.js";
import { showConfirmDialog, showChoiceDialog } from "/js/confirmDialog.js";

// Constants
const VIEW_MODE_STORAGE_KEY = "settingsActiveTab";
const DEFAULT_TAB = "agent";

// Field button actions (field id -> modal path)
const FIELD_BUTTON_MODAL_BY_ID = Object.freeze({
  mcp_servers_config: "settings/mcp/client/mcp-servers.html",
  backup_create: "settings/backup/backup.html",
  backup_restore: "settings/backup/restore.html",
  show_a2a_connection: "settings/a2a/a2a-connection.html",
  external_api_examples: "settings/external/api-examples.html",
});

// Helper for toasts
function toast(text, type = "info", timeout = 5000) {
  notificationStore.addFrontendToastOnly(type, text, "", timeout / 1000);
}

// Settings Store
const model = {
  // State
  isLoading: false,
  error: null,
  settings: null,
  additional: null,
  workdirFileStructureTestOutput: "",
  initialSettingsSnapshot: null,
  fineTuningApplyScope: "global",
  fineTuningApplyProject: "",
  fineTuningApplyProfile: "",
  fineTuningApplyTargetValue: "global",
  fineTuningTargetOptions: [],
  fineTuningSourceMap: {},
  fineTuningPendingOverrides: {},
  fineTuningPendingEnvActions: {},
  fineTuningManagedKeys: [],
  
  // Tab state
  _activeTab: DEFAULT_TAB,
  get activeTab() {
    return this._activeTab;
  },
  set activeTab(value) {
    const previous = this._activeTab;
    this._activeTab = value;
    this.applyActiveTab(previous, value);
  },

  // Lifecycle
  init() {
    // Restore persisted tab
    try {
      const saved = localStorage.getItem(VIEW_MODE_STORAGE_KEY);
      if (saved) this._activeTab = saved;
    } catch {}
  },

  async onOpen() {
    this.error = null;
    this.isLoading = true;
    
    try {
      const response = await API.callJsonApi("settings_get", null);
      if (response && response.settings) {
        this.settings = response.settings;
        this.additional = response.additional || null;
        this.fineTuningApplyProfile = this.settings.agent_profile || this.fineTuningApplyProfile || "agent0";
        this.initialSettingsSnapshot = JSON.parse(JSON.stringify(this.settings));
        try {
          await this.refreshFineTuningState();
        } catch (innerError) {
          console.warn("Fine-Tuning metadata refresh failed:", innerError);
        }
        this.scheduleFineTuningDecorators();
      } else {
        throw new Error("Invalid settings response");
      }
    } catch (e) {
      console.error("Failed to load settings:", e);
      this.error = e.message || "Failed to load settings";
      toast("Failed to load settings", "error");
    } finally {
      this.isLoading = false;
    }

    // Trigger tab activation for current tab
    this.applyActiveTab(null, this._activeTab);
  },

  cleanup() {
    this.settings = null;
    this.additional = null;
    this.error = null;
    this.isLoading = false;
  },

  // Tab management
  applyActiveTab(previous, current) {
    // Persist
    try {
      localStorage.setItem(VIEW_MODE_STORAGE_KEY, current);
    } catch {}
  },

  switchTab(tabName) {
    this.activeTab = tabName;
  },



  get apiKeyProviders() {
    const seen = new Set();
    const options = [];
    const addProvider = (prov) => {
      if (!prov?.value) return;
      const key = prov.value.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      options.push({ value: prov.value, label: prov.label || prov.value });
    };
    (this.additional?.chat_providers || []).forEach(addProvider);
    (this.additional?.embedding_providers || []).forEach(addProvider);
    options.sort((a, b) => a.label.localeCompare(b.label));
    return options;
  },

  // Save settings
  async saveSettings() {
    if (!this.settings) {
      toast("No settings to save", "warning");
      return false;
    }

    const pendingSummary = this.buildPendingFineTuningSummary();
    if (pendingSummary.length > 0) {
      const summaryHtml = pendingSummary.map((line) => `- ${line}`).join("<br>");
      const proceed = await showConfirmDialog({
        title: "Apply pending Fine-Tuning changes?",
        message: `Pending changes:<br>${summaryHtml}<br><br>Continue?`,
        confirmText: "Continue",
        cancelText: "Cancel",
        type: "warning",
      });
      if (!proceed) return false;
    }

    this.isLoading = true;
    try {
      const stagedScopedKeys = new Set([
        ...Object.keys(this.fineTuningPendingOverrides || {}),
        ...Object.keys(this.fineTuningPendingEnvActions || {}),
      ]);
      const stagedValues = {};
      const payloadSettings = JSON.parse(JSON.stringify(this.settings));
      for (const key of stagedScopedKeys) {
        stagedValues[key] = this.settings[key];
        if (
          this.initialSettingsSnapshot &&
          Object.prototype.hasOwnProperty.call(this.initialSettingsSnapshot, key)
        ) {
          payloadSettings[key] = this.initialSettingsSnapshot[key];
        }
      }
      const response = await API.callJsonApi("settings_set", { settings: payloadSettings });
      if (response && response.settings) {
        this.settings = response.settings;
        this.additional = response.additional || this.additional;
        const stagedOk = await this.applyPendingFineTuningChanges(stagedValues);
        if (!stagedOk) throw new Error("Failed to apply pending Fine-Tuning staged changes");
        toast("Settings saved successfully", "success");
        document.dispatchEvent(
          new CustomEvent("settings-updated", { detail: response.settings })
        );
        this.initialSettingsSnapshot = JSON.parse(JSON.stringify(this.settings));
        this.fineTuningPendingOverrides = {};
        this.fineTuningPendingEnvActions = {};
        await this.refreshFineTuningState();
        this.scheduleFineTuningDecorators();
        return true;
      } else {
        throw new Error("Failed to save settings");
      }
    } catch (e) {
      console.error("Failed to save settings:", e);
      toast("Failed to save settings: " + e.message, "error");
      return false;
    } finally {
      this.isLoading = false;
    }
  },

  get envOverrides() {
    return this.additional?.runtime_settings?.env_overrides || {};
  },

  isEnvOverridden(key) {
    return Object.prototype.hasOwnProperty.call(this.envOverrides, key);
  },

  getEnvOverrideValue(key) {
    return this.envOverrides[key];
  },

  getEnvOverrideKeys() {
    return Object.keys(this.envOverrides || {}).sort();
  },

  get fineTuningScopeOptions() {
    return this.fineTuningTargetOptions || [];
  },

  get fineTuningScopeDescription() {
    const scope = this.fineTuningApplyScope;
    if (scope === "global") return "Applies to global settings.json (general baseline).";
    if (scope === "profile") return "Applies to user profile settings.json (more specialized than global).";
    if (scope === "project") return "Applies to active project settings.json (specialized per project).";
    if (scope === "project_profile") return "Applies to active project+profile settings.json (most specialized non-env scope).";
    return "Writes A0_SET_* lock value to .env (always highest precedence).";
  },

  parseFineTuningTargetValue(targetValue) {
    const raw = String(targetValue || "global");
    if (raw === "global") return { scope: "global", profile: "", project: "" };
    if (raw === "env") return { scope: "env", profile: "", project: "" };
    if (raw.startsWith("profile::")) {
      const profile = raw.split("::")[1] || "";
      return { scope: "profile", profile, project: "" };
    }
    if (raw.startsWith("project::")) {
      const project = raw.split("::")[1] || "";
      return { scope: "project", profile: "", project };
    }
    if (raw.startsWith("project_profile::")) {
      const parts = raw.split("::");
      return { scope: "project_profile", project: parts[1] || "", profile: parts[2] || "" };
    }
    return { scope: "global", profile: "", project: "" };
  },

  async refreshFineTuningState() {
    const parsed = this.parseFineTuningTargetValue(this.fineTuningApplyTargetValue);
    this.fineTuningApplyScope = parsed.scope;
    this.fineTuningApplyProject = parsed.project || "";
    this.fineTuningApplyProfile =
      parsed.profile || this.settings?.agent_profile || this.fineTuningApplyProfile || "";
    const ctxid = globalThis.getContext?.() || "";
    const response = await API.callJsonApi("settings_fine_tuning_state_get", {
      profile: this.fineTuningApplyProfile || "",
      project: this.fineTuningApplyProject || "",
      ctxid,
    });
    this.fineTuningTargetOptions = response?.target_options || [];
    this.fineTuningSourceMap = response?.source_map || {};
    this.fineTuningManagedKeys = Object.keys(this.fineTuningSourceMap || {});
    const optionValues = new Set(
      (this.fineTuningTargetOptions || [])
        .filter((o) => !o.disabled)
        .map((o) => String(o.value))
    );
    if (!optionValues.has(String(this.fineTuningApplyTargetValue))) {
      this.fineTuningApplyTargetValue = optionValues.has("global")
        ? "global"
        : (this.fineTuningTargetOptions || []).find((o) => !o.disabled)?.value || "global";
    }
  },

  async onFineTuningTargetChanged() {
    try {
      await this.refreshFineTuningState();
    } catch (e) {
      toast(`Failed to refresh Fine-Tuning target metadata: ${e.message}`, "error");
    } finally {
      this.scheduleFineTuningDecorators();
    }
  },

  getSettingSourceMeta(key) {
    return this.fineTuningSourceMap?.[key] || {
      source: "default",
      source_label: "Defaults",
      source_without_env: "default",
      source_without_env_label: "Defaults",
      is_env_locked: false,
    };
  },

  getSettingEditState(key) {
    const selected = this.parseFineTuningTargetValue(this.fineTuningApplyTargetValue);
    if (selected.scope === "env") {
      return { state: "editable", readonly: false };
    }
    const meta = this.getSettingSourceMeta(key);
    const pendingOverride = !!this.fineTuningPendingOverrides?.[key];
    const pendingUnlock = this.fineTuningPendingEnvActions?.[key] || null;
    const envLockedNow = !!meta.is_env_locked && !pendingUnlock;
    if (envLockedNow) {
      return {
        state: "locked",
        readonly: true,
        label: "locked by .env",
      };
    }
    if (pendingOverride) return { state: "editable", readonly: false };
    const source = pendingUnlock ? meta.source_without_env : meta.source;
    const sourceLabel = pendingUnlock
      ? meta.source_without_env_label
      : meta.source_label;
    if (source === "default" || source === selected.scope) {
      return { state: "editable", readonly: false };
    }
    return {
      state: "inherited",
      readonly: true,
      label: `inherited from ${sourceLabel}`,
      inheritedSource: sourceLabel,
    };
  },

  extractSettingKeyFromModel(modelExpr) {
    const match = String(modelExpr || "").match(/\$store\.settings\.settings\.([A-Za-z0-9_]+)/);
    return match ? match[1] : "";
  },

  scheduleFineTuningDecorators() {
    setTimeout(() => this.refreshFineTuningFieldDecorators(), 0);
  },

  async handleSettingStateAction(key, state) {
    if (state === "locked") {
      const choice = await showChoiceDialog({
        title: "Unlock .env setting",
        message: `This will remove the '${key}' setting from .env, continue?`,
        choices: [
          { id: "remove_unset", label: "Remove and unset", variant: "confirm" },
          { id: "remove_set_global", label: "Remove and set in Global Settings", variant: "confirm" },
          { id: "cancel", label: "Cancel", variant: "cancel" },
        ],
        cancelId: "cancel",
        type: "warning",
      });
      if (!choice || choice === "cancel") return;
      this.fineTuningPendingEnvActions[key] = { mode: choice };
      if (choice === "remove_set_global") {
        this.fineTuningPendingOverrides[key] = { scope: "global", profile: "", project: "" };
      } else {
        delete this.fineTuningPendingOverrides[key];
      }
      this.scheduleFineTuningDecorators();
      return;
    }
    if (state === "inherited") {
      const meta = this.getSettingSourceMeta(key);
      const proceed = await showConfirmDialog({
        title: "Override inherited setting",
        message: `This will override the '${key}' setting from '${meta.source_label}', continue?`,
        confirmText: "Override setting",
        cancelText: "Cancel",
        type: "info",
      });
      if (!proceed) return;
      const target = this.parseFineTuningTargetValue(this.fineTuningApplyTargetValue);
      this.fineTuningPendingOverrides[key] = {
        scope: target.scope,
        profile: target.profile || "",
        project: target.project || "",
      };
      this.scheduleFineTuningDecorators();
    }
  },

  refreshFineTuningFieldDecorators() {
    const root = document.querySelector("[data-fine-tuning-root]");
    if (!root) return;
    const controls = root.querySelectorAll("[x-model]");
    controls.forEach((control) => {
      const key = this.extractSettingKeyFromModel(control.getAttribute("x-model"));
      if (!key || !this.settings || !(key in this.settings)) return;
      const editState = this.getSettingEditState(key);
      if (control.matches("input,select,textarea")) {
        control.disabled = !!editState.readonly;
      }
      const fieldControl = control.closest(".field-control");
      if (!fieldControl) return;
      const existing = fieldControl.querySelector(`.setting-source-row[data-setting-key="${key}"]`);
      if (editState.state === "editable") {
        existing?.remove();
        return;
      }
      let row = existing;
      if (!row) {
        row = document.createElement("div");
        row.className = "setting-source-row";
        row.setAttribute("data-setting-key", key);
        row.innerHTML = `
          <span class="setting-source-text"></span>
          <button type="button" class="setting-source-link"></button>
        `;
        fieldControl.appendChild(row);
      }
      row.querySelector(".setting-source-text").textContent = editState.label || "";
      const actionBtn = row.querySelector(".setting-source-link");
      actionBtn.textContent = editState.state === "locked" ? "unlock" : "override";
      actionBtn.onclick = () => this.handleSettingStateAction(key, editState.state);
    });
  },

  buildPendingFineTuningSummary() {
    const lines = [];
    const envActions = this.fineTuningPendingEnvActions || {};
    for (const [key, action] of Object.entries(envActions)) {
      if (action?.mode === "remove_set_global") {
        lines.push(`remove A0_SET_${key} from .env and set ${key} in Global Settings`);
      } else {
        lines.push(`remove A0_SET_${key} from .env`);
      }
    }
    for (const [key, target] of Object.entries(this.fineTuningPendingOverrides || {})) {
      if (envActions[key]?.mode === "remove_set_global") continue;
      const scope = target?.scope || "global";
      const profile = target?.profile ? `/${target.profile}` : "";
      const project = target?.project ? `/${target.project}` : "";
      lines.push(`override ${key} in ${scope}${project}${profile}`);
    }
    return lines;
  },

  async applyPendingFineTuningChanges(stagedValues = {}) {
    const ctxid = globalThis.getContext?.() || "";
    for (const [key] of Object.entries(this.fineTuningPendingEnvActions || {})) {
      const response = await API.callJsonApi("settings_env_override_unset", { key });
      if (response?.settings) {
        this.settings = response.settings;
        this.additional = response.additional || this.additional;
      }
    }
    for (const [key, target] of Object.entries(this.fineTuningPendingOverrides || {})) {
      const payload = {
        key,
        value: Object.prototype.hasOwnProperty.call(stagedValues, key)
          ? stagedValues[key]
          : this.settings[key],
        scope: target?.scope || "global",
        profile: target?.profile || "",
        project: target?.project || "",
        ctxid,
      };
      const response = await API.callJsonApi("settings_scope_override_set", payload);
      if (response?.settings) {
        this.settings = response.settings;
        this.additional = response.additional || this.additional;
      }
    }
    return true;
  },

  async persistSettingToEnv(key) {
    if (!this.settings || !(key in this.settings)) {
      toast(`Cannot persist unknown setting: ${key}`, "error");
      return false;
    }
    this.isLoading = true;
    try {
      const response = await API.callJsonApi("settings_env_override_set", {
        key,
        value: this.settings[key],
      });
      if (response && response.settings) {
        this.settings = response.settings;
        this.additional = response.additional || this.additional;
        toast(`Saved ${key} to .env override`, "success");
        document.dispatchEvent(
          new CustomEvent("settings-updated", { detail: response.settings })
        );
        return true;
      }
      throw new Error("Invalid response while saving env override");
    } catch (e) {
      console.error("Failed to persist env override:", e);
      toast(`Failed to save ${key} to .env: ${e.message}`, "error");
      return false;
    } finally {
      this.isLoading = false;
    }
  },

  async persistSettingToScope(key, scope = null) {
    if (!this.settings || !(key in this.settings)) {
      toast(`Cannot persist unknown setting: ${key}`, "error");
      return false;
    }
    const selectedScope = (scope || this.fineTuningApplyScope || "global").trim();
    this.isLoading = true;
    try {
      const ctxid = globalThis.getContext?.() || "";
      const payload = {
        key,
        value: this.settings[key],
        scope: selectedScope,
        profile: this.fineTuningApplyProfile || this.settings.agent_profile || "",
        project: this.fineTuningApplyProject || "",
        ctxid,
      };
      const response = await API.callJsonApi("settings_scope_override_set", payload);
      if (response && response.settings) {
        this.settings = response.settings;
        this.additional = response.additional || this.additional;
        toast(`Saved ${key} to ${selectedScope} scope`, "success");
        document.dispatchEvent(
          new CustomEvent("settings-updated", { detail: response.settings })
        );
        return true;
      }
      throw new Error("Invalid response while saving scoped override");
    } catch (e) {
      console.error("Failed to persist scoped override:", e);
      toast(`Failed to save ${key} for scope ${selectedScope}: ${e.message}`, "error");
      return false;
    } finally {
      this.isLoading = false;
    }
  },

  // Close the modal
  closeSettings() {
    window.closeModal("settings/settings.html");
  },

  // Save and close
  async saveAndClose() {
    const success = await this.saveSettings();
    if (success) {
      this.closeSettings();
    }
  },

  async testWorkdirFileStructure() {
    if (!this.settings) return;
    try {
      const response = await API.callJsonApi("settings_workdir_file_structure", {
        workdir_path: this.settings.workdir_path,
        workdir_max_depth: this.settings.workdir_max_depth,
        workdir_max_files: this.settings.workdir_max_files,
        workdir_max_folders: this.settings.workdir_max_folders,
        workdir_max_lines: this.settings.workdir_max_lines,
        workdir_gitignore: this.settings.workdir_gitignore,
      });
      this.workdirFileStructureTestOutput = response?.data || "";
      window.openModal("settings/agent/workdir-file-structure-test.html");
    } catch (e) {
      console.error("Error testing workdir file structure:", e);
      toast("Error testing workdir file structure", "error");
    }
  },

  // Field helpers for external components
  // Handle button field clicks (opens sub-modals)
  async handleFieldButton(field) {
    const modalPath = FIELD_BUTTON_MODAL_BY_ID[field?.id];
    if (modalPath) window.openModal(modalPath);
  },

  // Open settings modal from external callers
  async open(initialTab = null) {
    if (initialTab) {
      this._activeTab = initialTab;
    }
    await window.openModal("settings/settings.html");
  },
};

const store = createStore("settings", model);

export { store };

