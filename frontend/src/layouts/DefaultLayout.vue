<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useAppStore } from "@/stores/app";

const route = useRoute();
const appStore = useAppStore();

const activeMenu = computed(() => route.path);
const currentTitle = computed(() => (route.meta.title as string) ?? "");

interface MenuLeaf {
  index: string;
  title: string;
}

interface MenuItem extends MenuLeaf {
  icon: string;
  children?: MenuLeaf[];
}

const menu: MenuItem[] = [
  { index: "/dashboard", title: "驾驶舱", icon: "Odometer" },
  { index: "/accounts", title: "账号管理", icon: "Connection" },
  { index: "/messages", title: "消息中心", icon: "ChatDotRound" },
  { index: "/topics", title: "选题管理", icon: "Calendar" },
  { index: "/materials", title: "素材库", icon: "FolderOpened" },
  { index: "/content/create", title: "内容创作", icon: "EditPen" },
  { index: "/publish", title: "发布任务", icon: "Promotion" },
  {
    index: "/reports/content",
    title: "数据报表",
    icon: "DataAnalysis",
    children: [
      { index: "/reports/content", title: "内容大盘" },
      { index: "/reports/ads", title: "投流大盘" },
    ],
  },
  { index: "/settings", title: "系统设置", icon: "Setting" },
];
</script>

<template>
  <el-container class="h-full">
    <!-- 侧栏 -->
    <el-aside
      :width="appStore.sidebarCollapsed ? '64px' : '220px'"
      class="fp-aside transition-[width] duration-200"
    >
      <div class="fp-logo" :class="{ collapsed: appStore.sidebarCollapsed }">
        <span class="fp-logo-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" fill="none">
            <path
              d="M6 16h5l3-7 4 14 3-7h5"
              stroke="#fff"
              stroke-width="2.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </span>
        <span v-if="!appStore.sidebarCollapsed" class="fp-logo-text">心流 FlowPulse</span>
      </div>

      <el-scrollbar class="fp-menu-scroll">
        <el-menu
          :default-active="activeMenu"
          :collapse="appStore.sidebarCollapsed"
          :collapse-transition="false"
          router
          background-color="#0f1526"
          text-color="#a3aac2"
          active-text-color="#ffffff"
        >
          <template v-for="item in menu" :key="item.index">
            <el-sub-menu v-if="item.children" :index="item.index">
              <template #title>
                <el-icon><component :is="item.icon" /></el-icon>
                <span>{{ item.title }}</span>
              </template>
              <el-menu-item
                v-for="child in item.children"
                :key="child.index"
                :index="child.index"
              >
                {{ child.title }}
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="item.index">
              <el-icon><component :is="item.icon" /></el-icon>
              <template #title>{{ item.title }}</template>
            </el-menu-item>
          </template>
        </el-menu>
      </el-scrollbar>
    </el-aside>

    <el-container>
      <!-- 顶栏 -->
      <el-header class="fp-header" height="56px">
        <div class="flex items-center gap-3">
          <el-button text @click="appStore.toggleSidebar()">
            <el-icon :size="18">
              <component :is="appStore.sidebarCollapsed ? 'Expand' : 'Fold'" />
            </el-icon>
          </el-button>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/dashboard' }">工作台</el-breadcrumb-item>
            <el-breadcrumb-item v-if="currentTitle">{{ currentTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="flex items-center gap-4">
          <el-tooltip content="GitHub 仓库" placement="bottom">
            <a
              href="https://github.com/izetaiota/FlowPulse"
              target="_blank"
              rel="noopener"
              class="fp-gh-link"
            >
              <el-icon :size="18"><Link /></el-icon>
            </a>
          </el-tooltip>
          <el-dropdown>
            <span class="fp-user">
              <el-avatar :size="30" class="fp-avatar">创</el-avatar>
              <span class="hidden sm:inline">创作者</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>个人中心（规划中）</el-dropdown-item>
                <el-dropdown-item disabled>退出登录（规划中）</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <!-- 内容区 -->
      <el-main class="fp-main">
        <router-view v-slot="{ Component }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.fp-aside {
  display: flex;
  flex-direction: column;
  background-color: #0f1526;
  overflow: hidden;
}

.fp-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 56px;
  padding: 0 16px;
  flex: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.fp-logo.collapsed {
  justify-content: center;
  padding: 0;
}

.fp-logo-mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #6366f1, #a855f7);
}

.fp-logo-mark svg {
  width: 20px;
  height: 20px;
}

.fp-logo-text {
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 1px;
  white-space: nowrap;
}

.fp-menu-scroll {
  flex: 1;
}

.fp-menu-scroll :deep(.el-menu) {
  border-right: none;
}

.fp-menu-scroll :deep(.el-menu-item.is-active) {
  background-color: var(--fp-primary);
}

.fp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: #fff;
  border-bottom: 1px solid #e8eaf0;
  padding: 0 16px;
}

.fp-gh-link {
  display: grid;
  place-items: center;
  color: #64748b;
}

.fp-gh-link:hover {
  color: var(--fp-primary);
}

.fp-user {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #334155;
  outline: none;
}

.fp-avatar {
  background: linear-gradient(135deg, #6366f1, #a855f7);
  font-size: 13px;
}

.fp-main {
  padding: 16px;
  overflow-y: auto;
}
</style>
