<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { accountApi } from "@/api/accounts";
import { monitorApi } from "@/api/monitor";
import { douyinMonitorApi } from "@/api/douyin";
import { ksMonitorApi } from "@/api/ks";
import { tiktokApi } from "@/api/tiktok";
import { queueApi } from "@/api/queue";
import { downloadApi } from "@/api/download";

const router = useRouter();

interface Stat {
  label: string;
  value: string;
  trend?: string;
  icon: string;
  color: string;
}

const stats = ref<Stat[]>([]);
const loading = ref(false);

const recentItems = ref<Array<{ time: string; text: string; type: string }>>([]);
const totalMonitors = ref(0);
const totalWorks = ref(0);

async function loadStats() {
  loading.value = true;
  try {
    const [accounts, xhsMonitors, douyinMonitors, ksMonitors, tiktokMonitors, queue, downloads] =
      await Promise.all([
        accountApi.list().catch(() => ({ accounts: [] as never[] })),
        monitorApi.list().catch(() => ({ monitors: [] as never[] })),
        douyinMonitorApi.list().catch(() => ({ monitors: [] as never[] })),
        ksMonitorApi.list().catch(() => ({ monitors: [] as never[] })),
        tiktokApi.list().catch(() => ({ monitors: [] as never[] })),
        queueApi.list().catch(() => ({ items: [] as never[] })),
        downloadApi.list().catch(() => ({ tasks: [] as never[] })),
      ]);

    const monitorLists = [xhsMonitors.monitors, douyinMonitors.monitors, ksMonitors.monitors, tiktokMonitors.monitors];
    totalMonitors.value = monitorLists.reduce((sum, list) => sum + list.length, 0);
    totalWorks.value = monitorLists.reduce(
      (sum, list) => sum + list.reduce((s: number, m: { content_count?: number }) => s + (m.content_count || 0), 0),
      0,
    );

    const activeAccounts = accounts.accounts.filter((a: { status: string }) => a.status === "active").length;
    const runningTasks = queue.items.filter(
      (t: { status: string }) => t.status === "pending" || t.status === "running",
    ).length;
    const completedDownloads = downloads.tasks.filter(
      (t: { status: string }) => t.status === "completed",
    ).length;

    stats.value = [
      { label: "平台账号", value: String(activeAccounts), trend: `共 ${accounts.accounts.length} 个`, icon: "Connection", color: "#6d5ef2" },
      { label: "监控目标", value: String(totalMonitors.value), trend: `${totalWorks.value} 条作品`, icon: "Monitor", color: "#10b981" },
      { label: "进行中任务", value: String(runningTasks), trend: `${queue.items.length} 条记录`, icon: "VideoPlay", color: "#f59e0b" },
      { label: "已完成下载", value: String(completedDownloads), trend: `${downloads.tasks.length} 条任务`, icon: "Download", color: "#0ea5e9" },
    ];

    // 最近动态：跨平台作品 + 队列最近任务
    const items: Array<{ time: string; text: string; type: string }> = [];
    for (const item of queue.items.slice(0, 8)) {
      items.push({
        time: item.updated_at.replace("T", " ").slice(5, 16),
        text: `${item.kind}：${item.title || item.id}`,
        type: item.status === "completed" ? "success" : item.status === "failed" ? "warning" : "publish",
      });
    }
    recentItems.value = items;
  } finally {
    loading.value = false;
  }
}

const quickActions = [
  { title: "作品监控", desc: "多平台定时扫描", icon: "Monitor", path: "/xhs/monitor" },
  { title: "链接下载", desc: "粘贴文案一键下载", icon: "Download", path: "/materials" },
  { title: "发布任务", desc: "抖音创作中心发布", icon: "Promotion", path: "/publish" },
  { title: "私信中心", desc: "小红书/抖音会话", icon: "ChatDotRound", path: "/messages" },
];

function todoTag(type: string): { label: string; kind: "warning" | "primary" | "success" | "info" } {
  switch (type) {
    case "warning":
      return { label: "失败", kind: "warning" };
    case "success":
      return { label: "完成", kind: "success" };
    default:
      return { label: "进行中", kind: "info" };
  }
}

onMounted(loadStats);
</script>

<template>
  <div class="space-y-4">
    <!-- 欢迎横幅 -->
    <div class="fp-banner">
      <div>
        <h2 class="fp-banner-title">繁杂交给系统，创作进入心流</h2>
        <p class="fp-banner-desc">
          五平台账号已接入统一管理；监控、采集、下载、发布与私信在后台自动运转。
        </p>
      </div>
      <el-button type="primary" round @click="router.push('/xhs/monitor')">
        <el-icon class="mr-1"><Monitor /></el-icon>
        去监控
      </el-button>
    </div>

    <!-- 核心指标 -->
    <el-row :gutter="16" v-loading="loading">
      <el-col v-for="stat in stats" :key="stat.label" :xs="12" :sm="12" :md="6">
        <el-card shadow="never" class="fp-stat-card">
          <div class="fp-stat-icon" :style="{ backgroundColor: stat.color + '1a', color: stat.color }">
            <el-icon :size="20"><component :is="stat.icon" /></el-icon>
          </div>
          <div class="fp-stat-label">{{ stat.label }}</div>
          <div class="fp-stat-value">{{ stat.value }}</div>
          <div v-if="stat.trend" class="fp-stat-trend">{{ stat.trend }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <!-- 快捷入口 -->
      <el-col :xs="24" :md="10">
        <el-card shadow="never" class="h-full" header="快捷入口">
          <div class="grid grid-cols-2 gap-3">
            <div
              v-for="action in quickActions"
              :key="action.title"
              class="fp-action"
              @click="router.push(action.path)"
            >
              <el-icon :size="22" color="#6d5ef2"><component :is="action.icon" /></el-icon>
              <div>
                <div class="fp-action-title">{{ action.title }}</div>
                <div class="fp-action-desc">{{ action.desc }}</div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 最近动态 -->
      <el-col :xs="24" :md="14">
        <el-card shadow="never" class="h-full" header="最近任务动态">
          <div class="space-y-3">
            <div v-for="(item, i) in recentItems" :key="i" class="fp-todo">
              <el-tag :type="todoTag(item.type).kind" size="small" effect="light" round>
                {{ todoTag(item.type).label }}
              </el-tag>
              <span class="fp-todo-text">{{ item.text }}</span>
              <span class="fp-todo-time">{{ item.time }}</span>
            </div>
            <el-empty v-if="!recentItems.length" description="暂无任务动态" :image-size="60" />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.fp-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 24px;
  border-radius: 12px;
  color: #fff;
  background:
    radial-gradient(600px 240px at 15% 0%, rgba(99, 102, 241, 0.4), transparent 60%),
    radial-gradient(500px 240px at 90% 120%, rgba(34, 211, 238, 0.22), transparent 60%),
    #101728;
}

.fp-banner-title {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 1px;
}

.fp-banner-desc {
  margin: 0;
  font-size: 13px;
  color: rgba(226, 232, 240, 0.72);
}

.fp-stat-card {
  border-radius: 12px;
  position: relative;
}

.fp-stat-icon {
  position: absolute;
  top: 16px;
  right: 16px;
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
}

.fp-stat-label {
  color: #64748b;
  font-size: 13px;
}

.fp-stat-value {
  font-size: 26px;
  font-weight: 800;
  margin-top: 2px;
}

.fp-stat-trend {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 2px;
}

.fp-action {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px;
  border-radius: 10px;
  border: 1px solid #e8eaf0;
  cursor: pointer;
  transition: all 0.2s;
}

.fp-action:hover {
  border-color: #c7d2fe;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
}

.fp-action-title {
  font-size: 14px;
  font-weight: 600;
}

.fp-action-desc {
  font-size: 12px;
  color: #94a3b8;
}

.fp-todo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
}

.fp-todo-text {
  flex: 1;
  color: #334155;
}

.fp-todo-time {
  font-size: 12px;
  color: #94a3b8;
  white-space: nowrap;
}
</style>
