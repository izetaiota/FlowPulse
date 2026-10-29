<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  artifactUrl,
  transcribeApi,
  type TaskPage,
  type TaskResult,
  type TranscribeTask,
} from "@/api/transcribe";

// ---- 提交 ----
const input = ref("");
const submitting = ref(false);

async function submit() {
  if (!input.value.trim()) {
    ElMessage.warning("请粘贴抖音分享链接或完整分享文案");
    return;
  }
  submitting.value = true;
  try {
    await transcribeApi.create(input.value.trim());
    ElMessage.success("任务已创建，后台转写中");
    input.value = "";
    await loadTasks();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "创建失败");
  } finally {
    submitting.value = false;
  }
}

// ---- 任务列表 ----
const tasks = ref<TranscribeTask[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(false);
const loadError = ref("");

async function loadTasks() {
  loading.value = true;
  loadError.value = "";
  try {
    const page: TaskPage = await transcribeApi.list(20);
    tasks.value = page.items;
    cursor.value = page.next_cursor;
  } catch {
    loadError.value = "任务列表加载失败，请确认后端服务正常后重试。";
  } finally {
    loading.value = false;
  }
}

async function loadMore() {
  if (!cursor.value) return;
  const page: TaskPage = await transcribeApi.list(20, cursor.value);
  tasks.value.push(...page.items);
  cursor.value = page.next_cursor;
}

async function retry(task: TranscribeTask) {
  try {
    await transcribeApi.retry(task.id);
    ElMessage.success("已重新入队");
    await loadTasks();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "重试失败");
  }
}

function statusTag(status: string) {
  if (status === "completed") return { text: "完成", type: "success" as const };
  if (status === "failed") return { text: "失败", type: "danger" as const };
  if (status === "pending") return { text: "排队", type: "info" as const };
  return { text: "处理中", type: "warning" as const };
}

// ---- 详情抽屉 ----
const drawerVisible = ref(false);
const detailTask = ref<TranscribeTask | null>(null);
const result = ref<TaskResult | null>(null);
const resultLoading = ref(false);
const resultError = ref("");

async function openDetail(task: TranscribeTask) {
  detailTask.value = task;
  result.value = null;
  resultError.value = "";
  drawerVisible.value = true;
  resultLoading.value = true;
  try {
    result.value = await transcribeApi.result(task.id);
  } catch {
    resultError.value = "结果尚未生成或任务未完成，可稍后再打开。";
  } finally {
    resultLoading.value = false;
  }
}

function fmtTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

onMounted(loadTasks);
</script>

<template>
  <div class="space-y-4">
    <!-- 提交卡 -->
    <el-card shadow="never">
      <template #header><span class="font-bold">提交转写任务</span></template>
      <div class="flex gap-2">
        <el-input
          v-model="input"
          placeholder="粘贴抖音分享链接或完整分享文案（含标题/话题的那种整段文字也可以）"
          clearable
          @keyup.enter="submit"
        />
        <el-button type="primary" :loading="submitting" @click="submit">提交</el-button>
      </div>
      <div class="mt-2 text-xs text-gray-400">
        解析视频 → 提取内嵌字幕（无字幕时调用转写引擎）→ 产出 JSON / SRT / Markdown
      </div>
    </el-card>

    <!-- 任务列表 -->
    <el-card shadow="never">
      <template #header>
        <div class="flex items-center justify-between">
          <span class="font-bold">任务列表</span>
          <el-button size="small" :loading="loading" @click="loadTasks">刷新</el-button>
        </div>
      </template>
      <el-alert v-if="loadError && !tasks.length" type="error" :title="loadError" :closable="false" class="mb-3" />
      <el-table v-if="tasks.length" :data="tasks">
        <el-table-column label="标题" min-width="240">
          <template #default="{ row }">
            <el-link type="primary" @click="openDetail(row)">{{ row.title || row.input.slice(0, 40) }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="author" label="作者" width="120" />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status).type" size="small" round>{{ statusTag(row.status).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="80" align="center">
          <template #default="{ row }">{{ row.progress }}%</template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openDetail(row)">详情</el-button>
            <el-button v-if="row.status === 'failed'" size="small" text type="warning" @click="retry(row)">重试</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else-if="!loadError" description="还没有转写任务，粘贴抖音链接提交一个试试" />
      <el-button v-if="cursor" class="mt-3 w-full" size="small" @click="loadMore">加载更多</el-button>
    </el-card>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="detailTask?.title || '任务详情'" size="560px">
      <div v-if="detailTask" class="space-y-4">
        <el-descriptions :column="1" size="small" border>
          <el-descriptions-item label="状态">
            {{ statusTag(detailTask.status).text }} · {{ detailTask.progress }}%
            <span v-if="detailTask.message" class="text-xs text-gray-400">（{{ detailTask.message }}）</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="detailTask.author" label="作者">{{ detailTask.author }}</el-descriptions-item>
          <el-descriptions-item label="创建">{{ fmtTime(detailTask.created_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="detailTask.error" label="错误">
            <span class="text-red-500">{{ detailTask.error }}</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="detailTask.source_url" label="原文">
            <el-link :href="detailTask.source_url" target="_blank" type="primary">打开原视频</el-link>
          </el-descriptions-item>
        </el-descriptions>

        <div v-loading="resultLoading">
          <el-alert v-if="resultError" type="info" :title="resultError" :closable="false" />
          <template v-else-if="result">
            <div v-if="result.transcript?.segments?.length" class="transcript">
              <div v-for="(seg, i) in result.transcript.segments" :key="i" class="seg">{{ seg.text }}</div>
            </div>
            <div v-else class="text-sm text-gray-400">无转写文本</div>

            <div v-if="result.artifacts?.length" class="mt-4">
              <div class="mb-2 text-sm font-bold">下载产物</div>
              <el-link
                v-for="a in result.artifacts"
                :key="a.name"
                class="mr-3"
                type="primary"
                :href="artifactUrl(detailTask.id, a.name)"
                target="_blank"
              >{{ a.name }}（{{ (a.size / 1024).toFixed(1) }} KB）</el-link>
            </div>
          </template>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.transcript {
  max-height: 46vh;
  overflow: auto;
  background: #f8fafc;
  border-radius: 8px;
  padding: 14px;
  font-size: 14px;
  line-height: 1.9;
}

.seg + .seg {
  margin-top: 6px;
}
</style>
