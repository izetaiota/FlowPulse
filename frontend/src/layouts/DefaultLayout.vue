<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAppStore } from "@/stores/app";
import { useMenuStore } from "@/stores/menu";
import { useAuthStore } from "@/stores/auth";
import AppLogoMark from "@/components/AppLogoMark.vue";

const route = useRoute();
const router = useRouter();
const appStore = useAppStore();
const authStore = useAuthStore();

const activeMenu = computed(() => route.path);
const currentTitle = computed(() => (route.meta.title as string) ?? "");

function handleLogout() {
  authStore.logout();
  router.replace("/login");
}

const menuStore = useMenuStore();

onMounted(() => menuStore.load());
// 菜单数据驱动：后端 app_menus 表（失败时 store 内置兜底，导航不消失）
const menu = computed(() =>
  menuStore.menuTree.map((item) => ({
    index: item.path,
    title: item.title,
    icon: item.icon,
    children: item.children?.length
      ? item.children.map((child) => ({ index: child.path, title: child.title }))
      : undefined,
  })),
);

</script>

<template>
  <el-container class="h-full">
    <!-- 侧栏 -->
    <el-aside
      :width="appStore.sidebarCollapsed ? '64px' : '220px'"
      class="fp-aside transition-[width] duration-200"
    >
      <div class="fp-logo" :class="{ collapsed: appStore.sidebarCollapsed }">
        <AppLogoMark class="fp-logo-mark" />
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
              <!-- GitHub 官方标记（primer octicons mark-github，内联 SVG 免外部依赖） -->
              <svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" aria-hidden="true">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/>
              </svg>
            </a>
          </el-tooltip>
          <el-dropdown>
            <span class="fp-user">
              <el-avatar :size="30" class="fp-avatar">
                {{ (authStore.username || "本")[0] }}
              </el-avatar>
              <span class="hidden sm:inline">{{ authStore.username || "本地" }}</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="authStore.enabled" @click="handleLogout">
                  退出登录
                </el-dropdown-item>
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
  width: 30px;
  height: 30px;
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
