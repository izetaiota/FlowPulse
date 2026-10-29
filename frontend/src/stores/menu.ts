import { defineStore } from "pinia";
import { menuApi, type MenuItemData } from "@/api/menu";

/** 后端不可用时的兜底菜单（与后端默认种子一致），保证导航永不消失 */
export const FALLBACK_MENUS: MenuItemData[] = [
  { id: "dashboard", title: "驾驶舱", path: "/dashboard", icon: "Odometer", parent: "", visible: true },
  { id: "accounts", title: "账号管理", path: "/accounts", icon: "Connection", parent: "", visible: true },
  { id: "messages", title: "消息中心", path: "/messages", icon: "ChatDotRound", parent: "", visible: true },
  { id: "topics", title: "选题管理", path: "/topics", icon: "Calendar", parent: "", visible: true },
  { id: "materials", title: "素材库", path: "/materials", icon: "FolderOpened", parent: "", visible: true },
  { id: "weread", title: "公众号订阅", path: "/weread", icon: "Reading", parent: "", visible: true },
  { id: "xhs", title: "小红书工作台", path: "/xhs", icon: "PictureFilled", parent: "", visible: true },
  { id: "transcribe", title: "转写任务", path: "/transcribe", icon: "VideoPlay", parent: "", visible: true },
  { id: "content-create", title: "内容创作", path: "/content/create", icon: "EditPen", parent: "", visible: true },
  { id: "publish", title: "发布任务", path: "/publish", icon: "Promotion", parent: "", visible: true },
  { id: "reports", title: "数据报表", path: "/reports/content", icon: "DataAnalysis", parent: "", visible: true },
  { id: "reports-content", title: "内容大盘", path: "/reports/content", icon: "", parent: "reports", visible: true },
  { id: "reports-ads", title: "投流大盘", path: "/reports/ads", icon: "", parent: "reports", visible: true },
  { id: "settings", title: "系统设置", path: "/settings", icon: "Setting", parent: "", visible: true },
];

/** 侧栏菜单（数据驱动，来自后端 app_menus 表 / menus.json） */
export const useMenuStore = defineStore("menu", {
  state: () => ({
    items: [] as MenuItemData[],
    loaded: false,
    /** 使用的是否为兜底数据（后端不可用） */
    fallback: false,
  }),

  getters: {
    menuTree(state): Array<MenuItemData & { children?: MenuItemData[] }> {
      const visible = state.items.filter((i) => i.visible);
      const tops = visible.filter((i) => !i.parent);
      return tops.map((top) => ({
        ...top,
        children: visible.filter((i) => i.parent === top.id),
      }));
    },
  },

  actions: {
    async load(force = false) {
      if (this.loaded && !force) return;
      try {
        const { menus } = await menuApi.list();
        this.items = menus;
        this.fallback = false;
      } catch {
        this.items = FALLBACK_MENUS;
        this.fallback = true;
      }
      this.loaded = true;
    },
  },
});
