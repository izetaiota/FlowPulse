import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import DefaultLayout from "@/layouts/DefaultLayout.vue";

/**
 * 路由与 plan.md「前端页面结构」一一对应：
 * 驾驶舱 / 账号管理 / 消息中心 / 选题管理 / 素材库 /
 * 内容创作 / 发布任务 / 数据报表（内容大盘+投流大盘）/ 系统设置
 */
const routes: RouteRecordRaw[] = [
  {
    path: "/",
    component: DefaultLayout,
    redirect: "/dashboard",
    children: [
      {
        path: "dashboard",
        name: "dashboard",
        component: () => import("@/views/dashboard/index.vue"),
        meta: { title: "驾驶舱", icon: "Odometer" },
      },
      {
        path: "accounts",
        name: "accounts",
        component: () => import("@/views/accounts/index.vue"),
        meta: { title: "账号管理", icon: "Connection" },
      },
      {
        path: "messages",
        name: "messages",
        component: () => import("@/views/messages/index.vue"),
        meta: { title: "消息中心", icon: "ChatDotRound" },
      },
      {
        path: "topics",
        name: "topics",
        component: () => import("@/views/topics/index.vue"),
        meta: { title: "选题管理", icon: "Calendar" },
      },
      {
        path: "materials",
        name: "materials",
        component: () => import("@/views/materials/index.vue"),
        meta: { title: "素材库", icon: "FolderOpened" },
      },
      {
        path: "weread",
        name: "weread",
        component: () => import("@/views/weread/index.vue"),
        meta: { title: "公众号订阅", icon: "Reading" },
      },
      {
        path: "content/create",
        name: "content-create",
        component: () => import("@/views/content/create.vue"),
        meta: { title: "内容创作", icon: "EditPen" },
      },
      {
        path: "publish",
        name: "publish",
        component: () => import("@/views/publish/index.vue"),
        meta: { title: "发布任务", icon: "Promotion" },
      },
      {
        path: "reports/content",
        name: "reports-content",
        component: () => import("@/views/reports/content.vue"),
        meta: { title: "内容大盘", icon: "DataAnalysis" },
      },
      {
        path: "reports/ads",
        name: "reports-ads",
        component: () => import("@/views/reports/ads.vue"),
        meta: { title: "投流大盘", icon: "TrendCharts" },
      },
      {
        path: "settings",
        name: "settings",
        component: () => import("@/views/settings/index.vue"),
        meta: { title: "系统设置", icon: "Setting" },
      },
    ],
  },
  {
    path: "/:pathMatch(.*)*",
    redirect: "/dashboard",
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.afterEach((to) => {
  const base = import.meta.env.VITE_APP_TITLE || "心流 FlowPulse 工作台";
  const title = to.meta.title as string | undefined;
  document.title = title ? `${title} · ${base}` : base;
});

export default router;
