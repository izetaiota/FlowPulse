<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import client from "@/api/client";
import { downloadApi, type DownloadTask, type MediaEntry } from "@/api/download";

// ---- 链接下载 ----
const inputText = ref("");
const submitting = ref(false);
const tasks = ref<DownloadTask[]>([]);
const retryingId = ref("");
let timer: ReturnType<typeof setInterval> | null = null;

async function loadTasks() {
  try {
    tasks.value = (await downloadApi.list()).tasks;
  } catch {
    // 轮询失败静默；首次加载由 submit/refresh 路径提示
  }
}

async function submit() {
  if (!inputText.value.trim()) {
    ElMessage.warning("请粘贴分享文案或链接");
    return;
  }
  submitting.value = true;
  try {
    const result = await downloadApi.submit(inputText.value.trim());
    ElMessage.success(`已创建 ${result.tasks.length} 个下载任务`);
    inputText.value = "";
    await loadTasks();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "提交失败");
  } finally {
    submitting.value = false;
  }
}

async function retry(task: DownloadTask) {
  retryingId.value = task.id;
  try {
    await downloadApi.retry(task.id);
    ElMessage.success("已重新入队");
    await loadTasks();
  } catch {
    ElMessage.error("重试失败");
  } finally {
    retryingId.value = "";
  }
}

async function removeTask(task: DownloadTask) {
  try {
    await ElMessageBox.confirm(`删除任务「${task.title || task.url}」及其已下载文件？`, "删除任务", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await downloadApi.remove(task.id);
    ElMessage.success("已删除");
    await Promise.all([loadTasks(), loadFiles()]);
  } catch {
    ElMessage.error("删除失败");
  }
}

// 转写打通：抖音任务的原始链接提交转写管线
async function toTranscribe(task: DownloadTask) {
  try {
    await client.post("/v1/tasks/transcribe", { input: task.url });
    ElMessage.success("已提交转写，到「转写任务」页查看进度");
  } catch {
    ElMessage.error("提交转写失败");
  }
}

// 轮询：有进行中任务时每 5 秒刷新
const hasActive = computed(() => tasks.value.some((t) => t.status === "pending" || t.status === "running"));
function ensureTimer() {
  if (!timer && hasActive.value) {
    timer = setInterval(() => {
      if (!hasActive.value) {
        if (timer) clearInterval(timer);
        timer = null;
        loadFiles();
        return;
      }
      loadTasks();
    }, 5000);
  }
}

function statusTag(status: string): { label: string; type: "success" | "danger" | "primary" | "info" } {
  if (status === "completed") return { label: "已完成", type: "success" };
  if (status === "failed") return { label: "失败", type: "danger" };
  if (status === "running") return { label: "下载中", type: "primary" };
  return { label: "排队中", type: "info" };
}

function sourceLabel(source: string): string {
  const labels: Record<string, string> = { douyin: "抖音", bilibili: "B站", xhs: "小红书", other: "链接" };
  return labels[source] ?? source;
}

function formatSize(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(iso: string): string {
  return iso.replace("T", " ").slice(0, 19);
}

// ---- 媒体库 ----
const mediaRoot = ref("downloads");
const mediaPath = ref("");
const entries = ref<MediaEntry[]>([]);
const filesLoading = ref(false);
const previewVisible = ref(false);
const previewUrl = ref("");
const previewIsVideo = ref(false);

const breadcrumbs = computed(() => {
  const crumbs = [{ name: "根目录", path: "" }];
  if (mediaPath.value) {
    let acc = "";
    for (const part of mediaPath.value.split("/")) {
      acc = acc ? `${acc}/${part}` : part;
      crumbs.push({ name: part, path: acc });
    }
  }
  return crumbs;
});

async function loadFiles() {
  filesLoading.value = true;
  try {
    const result = await downloadApi.listFiles(mediaRoot.value, mediaPath.value);
    entries.value = result.entries;
  } catch {
    ElMessage.error("媒体库加载失败");
  } finally {
    filesLoading.value = false;
  }
}

function enterDirectory(entry: MediaEntry) {
  if (!entry.is_dir) return;
  mediaPath.value = entry.path;
  loadFiles();
}

function navigateTo(path: string) {
  mediaPath.value = path;
  loadFiles();
}

function openPreview(entry: MediaEntry) {
  if (!entry.previewable) return;
  previewUrl.value = downloadApi.fileUrl(mediaRoot.value, entry.path);
  previewIsVideo.value = /\.(mp4|webm|mov|mkv|flv)$/i.test(entry.name);
  previewVisible.value = true;
}

async function removeEntry(entry: MediaEntry) {
  try {
    await ElMessageBox.confirm(`删除「${entry.name}」${entry.is_dir ? "及其内容" : ""}？`, "删除文件", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await downloadApi.removeFile(mediaRoot.value, entry.path);
    ElMessage.success("已删除");
    await Promise.all([loadFiles(), loadTasks()]);
  } catch {
    ElMessage.error("删除失败");
  }
}

async function refreshAll() {
  await Promise.all([loadTasks(), loadFiles()]);
  ensureTimer();
}

onMounted(refreshAll);
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="space-y-4">
    <!-- 链接下载 -->
    <el-card shadow="never">
      <template #header>
        <span class="font-bold">链接下载</span>
        <span class="ml-3 text-xs text-slate-400">
          粘贴分享文案（抖音 / B站 / 小红书等），自动抽链下载，产物进入媒体库
        </span>
      </template>
      <div class="flex gap-3">
        <el-input
          v-model="inputText"
          type="textarea"
          :rows="2"
          placeholder="粘贴分享文案或链接，可含多行多个链接，如：https://v.douyin.com/xxxx/"
        />
        <el-button type="primary" :loading="submitting" @click="submit" style="height: fit-content">
          下载
        </el-button>
      </div>

      <el-table v-if="tasks.length" :data="tasks" class="mt-3" size="small">
        <el-table-column label="来源" width="80">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ sourceLabel(row.source) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标题" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.title || row.url }}</template>
        </el-table-column>
        <el-table-column label="状态" width="160">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag(row.status).type">
              {{ statusTag(row.status).label }}
            </el-tag>
            <el-progress
              v-if="row.status === 'running'"
              :percentage="row.progress"
              :stroke-width="6"
              class="mt-1"
            />
            <el-tooltip v-else-if="row.error" :content="row.error" placement="top">
              <el-icon class="ml-1 align-middle text-slate-400"><WarningFilled /></el-icon>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.source === 'douyin' && row.status === 'completed'"
              size="small"
              type="primary"
              plain
              @click="toTranscribe(row)"
            >
              转写
            </el-button>
            <el-button
              v-if="row.status === 'failed'"
              size="small"
              :loading="retryingId === row.id"
              @click="retry(row)"
            >
              重试
            </el-button>
            <el-button size="small" type="danger" plain @click="removeTask(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 媒体库 -->
    <el-card shadow="never" v-loading="filesLoading">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <span class="font-bold">媒体库</span>
            <el-radio-group
              v-model="mediaRoot"
              size="small"
              @change="
                mediaPath = '';
                loadFiles();
              "
            >
              <el-radio-button value="downloads">下载产物</el-radio-button>
              <el-radio-button value="xhs">小红书任务</el-radio-button>
            </el-radio-group>
          </div>
          <el-button size="small" @click="loadFiles">刷新</el-button>
        </div>
      </template>

      <el-breadcrumb separator="/" class="mb-3">
        <el-breadcrumb-item v-for="crumb in breadcrumbs" :key="crumb.path">
          <a class="fp-crumb" @click="navigateTo(crumb.path)">{{ crumb.name }}</a>
        </el-breadcrumb-item>
      </el-breadcrumb>

      <el-table :data="entries" size="small">
        <el-table-column label="名称" min-width="280">
          <template #default="{ row }">
            <span v-if="row.is_dir" class="fp-entry" @click="enterDirectory(row)">
              <el-icon class="mr-1"><FolderOpened /></el-icon>{{ row.name }}
            </span>
            <span v-else class="fp-entry" :class="{ 'fp-previewable': row.previewable }" @click="openPreview(row)">
              {{ row.name }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ row.is_dir ? "—" : formatSize(row.size) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_dir ? 'warning' : 'info'" effect="plain">
              {{ row.is_dir ? "目录" : "文件" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="修改时间" width="170">
          <template #default="{ row }">
            {{ new Date(row.mtime * 1000).toISOString().replace("T", " ").slice(0, 19) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="removeEntry(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无文件：下载任务完成后产物会出现在这里" />
        </template>
      </el-table>
    </el-card>

    <!-- 预览弹窗 -->
    <el-dialog v-model="previewVisible" :title="previewIsVideo ? '视频预览' : '图片预览'" width="720px">
      <video v-if="previewIsVideo" :src="previewUrl" controls style="width: 100%" />
      <img v-else :src="previewUrl" style="width: 100%" alt="预览" />
    </el-dialog>
  </div>
</template>

<style scoped>
.fp-crumb {
  cursor: pointer;
  color: var(--el-color-primary);
}

.fp-entry {
  cursor: default;
}

.fp-entry.fp-previewable {
  cursor: pointer;
  color: var(--el-color-primary);
}

.fp-entry.fp-previewable:hover {
  text-decoration: underline;
}
</style>
