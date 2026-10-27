<script setup lang="ts">
import { useRouter } from "vue-router";

const router = useRouter();

interface Stat {
  label: string;
  value: string;
  trend?: string;
  icon: string;
  color: string;
}

// 占位数据：待后端驾驶舱 API 接入后替换
const stats: Stat[] = [
  { label: "待回复消息", value: "12", trend: "条未读", icon: "ChatDotRound", color: "#f59e0b" },
  { label: "今日阅读", value: "8,432", trend: "+12.4%", icon: "View", color: "#10b981" },
  { label: "今日投流消耗", value: "¥1,208", icon: "Coin", color: "#6d5ef2" },
  { label: "整体 ROI", value: "3.2×", icon: "TrendCharts", color: "#0ea5e9" },
];

const quickActions = [
  { title: "新建选题", desc: "记录一个灵感", icon: "Calendar", path: "/topics" },
  { title: "创作内容", desc: "一份原稿多平台", icon: "EditPen", path: "/content/create" },
  { title: "素材库", desc: "上传与管理素材", icon: "FolderOpened", path: "/materials" },
  { title: "消息中心", desc: "回复粉丝互动", icon: "ChatDotRound", path: "/messages" },
];

const todos = [
  { time: "今天 18:00", text: "《秋日好物清单》定时分发到小红书", type: "publish" },
  { time: "2 小时前", text: "公众号授权即将过期，请重新绑定", type: "warning" },
  { time: "今天", text: "3 条小红书私信待回复（意向咨询）", type: "message" },
  { time: "昨日", text: "抖音《收纳教程》进入 7 日爆款榜", type: "success" },
];

function todoTag(type: string): { label: string; kind: "warning" | "primary" | "success" | "info" } {
  switch (type) {
    case "warning":
      return { label: "告警", kind: "warning" };
    case "message":
      return { label: "互动", kind: "primary" };
    case "success":
      return { label: "爆款", kind: "success" };
    default:
      return { label: "发布", kind: "info" };
  }
}
</script>

<template>
  <div class="space-y-4">
    <!-- 欢迎横幅 -->
    <div class="fp-banner">
      <div>
        <h2 class="fp-banner-title">繁杂交给系统，创作进入心流</h2>
        <p class="fp-banner-desc">
          欢迎回到驾驶舱，这里汇总你的消息、内容与投流数据。当前数据为占位示例，待后端 API 接入。
        </p>
      </div>
      <el-button type="primary" round @click="router.push('/content/create')">
        <el-icon class="mr-1"><EditPen /></el-icon>
        开始创作
      </el-button>
    </div>

    <!-- 核心指标 -->
    <el-row :gutter="16">
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

      <!-- 待办与动态 -->
      <el-col :xs="24" :md="14">
        <el-card shadow="never" class="h-full" header="待办与动态">
          <div class="space-y-3">
            <div v-for="(todo, i) in todos" :key="i" class="fp-todo">
              <el-tag :type="todoTag(todo.type).kind" size="small" effect="light" round>
                {{ todoTag(todo.type).label }}
              </el-tag>
              <span class="fp-todo-text">{{ todo.text }}</span>
              <span class="fp-todo-time">{{ todo.time }}</span>
            </div>
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
  color: #10b981;
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
