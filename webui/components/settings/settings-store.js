import { createStore } from "/js/AlpineStore.js";
import * as API from "/js/api.js";
import { store as notificationStore } from "/components/notifications/notification-store.js";

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
  fineTuningApplyScope: "global",
  fineTuningApplyProject: "",
  fineTuningApplyProfile: "",
  
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

    this.isLoading = true;
    try {
      const response = await API.callJsonApi("settings_set", { settings: this.settings });
      if (response && response.settings) {
        this.settings = response.settings;
        this.additional = response.additional || this.additional;
        toast("Settings saved successfully", "success");
        document.dispatchEvent(
          new CustomEvent("settings-updated", { detail: response.settings })
        );
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
    const opts = [
      { value: "global", label: "Global (usr/settings.json)" },
      { value: "profile", label: "Profile (usr/agents/<profile>/settings.json)" },
      { value: "project", label: "Project (.a0proj/settings.json)" },
      { value: "project_profile", label: "Project + Profile (.a0proj/agents/<profile>/settings.json)" },
      { value: "env", label: "Environment lock (.env A0_SET_*)" },
    ];
    return opts;
  },

  get fineTuningScopeDescription() {
    const scope = this.fineTuningApplyScope;
    if (scope === "global") return "Applies to global settings.json (general baseline).";
    if (scope === "profile") return "Applies to user profile settings.json (more specialized than global).";
    if (scope === "project") return "Applies to active project settings.json (specialized per project).";
    if (scope === "project_profile") return "Applies to active project+profile settings.json (most specialized non-env scope).";
    return "Writes A0_SET_* lock value to .env (always highest precedence).";
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

