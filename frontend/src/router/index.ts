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
        path: "xhs",
        name: "xhs",
        component: () => import("@/views/xhs/index.vue"),
        meta: { title: "小红书工作台", icon: "PictureFilled" },
      },
      {
        path: "xhs/monitor",
        name: "xhs-monitor",
        component: () => import("@/views/xhs/monitor.vue"),
        meta: { title: "作品监控", icon: "Monitor" },
      },
      {
        path: "channels",
        name: "channels",
        component: () => import("@/views/channels/index.vue"),
        meta: { title: "视频号", icon: "VideoCameraFilled" },
      },
      {
        path: "transcribe",
        name: "transcribe",
        component: () => import("@/views/transcribe/index.vue"),
        meta: { title: "转写任务", icon: "VideoPlay" },
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
    path: "/login",
    name: "login",
    component: () => import("@/views/login/index.vue"),
    meta: { title: "登录", public: true },
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

// 登录守卫：后端启用鉴权（ADMIN_PASSWORD）且未登录时，全部页面跳登录页
router.beforeEach(async (to) => {
  const { useAuthStore } = await import("@/stores/auth");
  const auth = useAuthStore();
  if (!auth.loaded) {
    try {
      await auth.loadSession();
    } catch {
      auth.loaded = true; // 探测失败不阻塞页面（后端未启动时保持可浏览）
    }
  }
  if (auth.enabled && !auth.token && !to.meta.public) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && auth.isLoggedIn) {
    return { path: "/" };
  }
  return true;
});

router.afterEach((to) => {
  const base = import.meta.env.VITE_APP_TITLE || "心流 FlowPulse 工作台";
  const title = to.meta.title as string | undefined;
  document.title = title ? `${title} · ${base}` : base;
});

export default router;
