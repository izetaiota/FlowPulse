<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { queueApi, type QueueItem } from "@/api/queue";

const items = ref<QueueItem[]>([]);
const loading = ref(false);
const retryingId = ref("");
let timer: ReturnType<typeof setInterval> | null = null;

async function load(silent = false) {
  if (!silent) loading.value = true;
  try {
    const result = await queueApi.list();
    items.value = result.items;
  } catch {
    if (!silent) ElMessage.error("任务动态加载失败");
  } finally {
    loading.value = false;
  }
}

async function retry(item: QueueItem) {
  retryingId.value = item.id;
  try {
    const result = await queueApi.retry(item.source, item.id);
    ElMessage.success(`已重新入队：${result.message || "重试中"}`);
    await load(true);
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data
      ?.detail;
    ElMessage.error(detail || "重试失败");
  } finally {
    retryingId.value = "";
  }
}

function statusTag(status: string): "success" | "danger" | "primary" | "info" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "pending" || status === "running") return "primary";
  return "info";
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "排队中",
    resolving: "解析中",
    downloading: "下载中",
    extracting_audio: "提取音频",
    transcribing: "转写中",
    rendering: "整理产物",
    running: "抓取中",
    completed: "已完成",
    failed: "失败",
  };
  return labels[status] ?? status;
}

function formatTime(iso: string): string {
  return iso.replace("T", " ").slice(0, 19);
}

onMounted(() => {
  load();
  // 进行中任务的轻量自动刷新（失败静默，不打扰）
  timer = setInterval(() => load(true), 10000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="space-y-4">
    <el-card shadow="never">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="fp-card-title">任务动态</h2>
          <p class="fp-card-desc">
            汇总抖音转写与小红书抓取任务，按更新时间倒序；失败任务可重试。
            私信 / 评论聚合待后续阶段接入。
          </p>
        </div>
        <el-button @click="load()" :loading="loading">刷新</el-button>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading">
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            <el-tag :type="row.source === 'douyin' ? 'primary' : 'danger'" effect="plain">
              {{ row.kind }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="消息" min-width="160" show-overflow-tooltip />
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">
            <span>{{ formatTime(row.updated_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.retryable"
              size="small"
              :loading="retryingId === row.id"
              @click="retry(row)"
            >
              重试
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无任务：提交转写或小红书抓取后在这里查看进度" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.fp-card-title {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 700;
}

.fp-card-desc {
  margin: 0;
  font-size: 13px;
  color: #64748b;
}
</style>
