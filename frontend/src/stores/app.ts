import { defineStore } from "pinia";

/** 全局界面状态（侧栏折叠状态本地持久化） */
export const useAppStore = defineStore("app", {
  state: () => ({
    sidebarCollapsed: false,
  }),
  actions: {
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed;
    },
  },
  persist: true,
});
