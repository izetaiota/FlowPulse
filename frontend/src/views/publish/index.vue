<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { publishApi, type PublishMediaFile, type PublishTask } from "@/api/publish";

const tasks = ref<PublishTask[]>([]);
const mediaFiles = ref<PublishMediaFile[]>([]);
const loading = ref(false);
let timer: ReturnType<typeof setInterval> | null = null;

async function load() {
  loading.value = true;
  try {
    const [taskResult, mediaResult] = await Promise.all([
      publishApi.list(),
      publishApi.mediaFiles(),
    ]);
    tasks.value = taskResult.tasks;
    mediaFiles.value = mediaResult.files;
  } catch {
    ElMessage.error("发布任务加载失败");
  } finally {
    loading.value = false;
  }
}

const hasActive = computed(() =>
  tasks.value.some((t) => t.status === "pending" || t.status === "publishing"),
);

function ensureTimer() {
  if (!timer && hasActive.value) {
    timer = setInterval(() => {
      load();
      if (!hasActive.value && timer) {
        clearInterval(timer);
        timer = null;
      }
    }, 5000);
  }
}

function statusTag(status: string): { label: string; type: "success" | "danger" | "primary" | "info" | "warning" } {
  const map: Record<string, { label: string; type: "success" | "danger" | "primary" | "info" | "warning" }> = {
    draft: { label: "草稿", type: "info" },
    pending: { label: "排队中", type: "primary" },
    publishing: { label: "发布中", type: "warning" },
    done: { label: "已发布", type: "success" },
    failed: { label: "失败", type: "danger" },
    canceled: { label: "已取消", type: "info" },
  };
  return map[status] ?? { label: status, type: "info" };
}

function visibilityLabel(v: string): string {
  return { public: "公开", friends: "好友可见", private: "仅自己可见" }[v] ?? v;
}

function formatSize(bytes: number): string {
  if (!bytes) return "—";
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(iso: string | null): string {
  return iso ? iso.replace("T", " ").slice(0, 19) : "—";
}

// ---- 新建草稿 ----
const createVisible = ref(false);
const creating = ref(false);
const form = ref({
  title: "",
  desc: "",
  topics: "",
  media_paths: [] as string[],
  visibility: "public",
  allow_save: true,
});

function openCreate() {
  form.value = { title: "", desc: "", topics: "", media_paths: [], visibility: "public", allow_save: true };
  createVisible.value = true;
}

async function submitCreate(publishNow: boolean) {
  if (!form.value.media_paths.length) {
    ElMessage.warning("请从媒体库选择视频/图片文件");
    return;
  }
  creating.value = true;
  try {
    const task = await publishApi.create(form.value);
    if (publishNow) {
      await publishApi.submit(task.id);
      ElMessage.success("已加入发布队列：将弹出浏览器窗口执行发布，如遇验证码请在窗口中手动完成");
    } else {
      ElMessage.success("草稿已保存");
    }
    createVisible.value = false;
    await load();
    ensureTimer();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "创建失败");
  } finally {
    creating.value = false;
  }
}

async function submitTask(task: PublishTask) {
  try {
    await publishApi.submit(task.id);
    ElMessage.success("已加入发布队列");
    await load();
    ensureTimer();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "提交失败");
  }
}

async function cancelTask(task: PublishTask) {
  try {
    await publishApi.cancel(task.id);
    ElMessage.success("已取消");
    await load();
  } catch {
    ElMessage.error("取消失败");
  }
}

async function removeTask(task: PublishTask) {
  try {
    await ElMessageBox.confirm(`删除发布任务「${task.title || task.media_paths[0]}」？`, "删除", {
      type: "warning",
    });
  } catch {
    return;
  }
  try {
    await publishApi.remove(task.id);
    ElMessage.success("已删除");
    await load();
  } catch {
    ElMessage.error("删除失败");
  }
}

onMounted(() => {
  load();
  ensureTimer();
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="space-y-4">
    <el-card shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span class="font-bold">抖音发布队列</span>
            <span class="ml-3 text-xs text-slate-400">
              浏览器自动化创作中心发布；遇短信/扫码/滑块验证会在弹出窗口等待你手动完成（最多 5 分钟）
            </span>
          </div>
          <div class="flex gap-2">
            <el-button @click="load" :loading="loading">刷新</el-button>
            <el-button type="primary" @click="openCreate">新建发布</el-button>
          </div>
        </div>
      </template>

      <el-table :data="tasks">
        <el-table-column label="标题" min-width="160">
          <template #default="{ row }">{{ row.title || "(无标题)" }}</template>
        </el-table-column>
        <el-table-column label="媒体文件" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.media_paths.join("、") }}</template>
        </el-table-column>
        <el-table-column label="可见性" width="100">
          <template #default="{ row }">{{ visibilityLabel(row.visibility) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status).type">{{ statusTag(row.status).label }}</el-tag>
            <el-tooltip v-if="row.error" :content="row.error" placement="top">
              <el-icon class="ml-1 align-middle text-slate-400"><WarningFilled /></el-icon>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'draft' || row.status === 'failed'"
              size="small"
              type="primary"
              @click="submitTask(row)"
            >
              发布
            </el-button>
            <el-button v-if="row.status === 'draft' || row.status === 'pending'" size="small" @click="cancelTask(row)">
              取消
            </el-button>
            <el-button v-if="row.status !== 'publishing'" size="small" type="danger" plain @click="removeTask(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无发布任务：从媒体库选一个视频创建发布（需先在「作品监控」页登录抖音）" />
        </template>
      </el-table>
    </el-card>

    <!-- 新建发布弹窗 -->
    <el-dialog v-model="createVisible" title="新建抖音发布" width="560px">
      <el-form label-width="100px">
        <el-form-item label="媒体文件">
          <el-select v-model="form.media_paths" multiple filterable style="width: 100%" placeholder="从媒体库选择（下载产物）">
            <el-option v-for="f in mediaFiles" :key="f.path" :label="`${f.name}（${formatSize(f.size)}）`" :value="f.path" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="form.title" maxlength="30" placeholder="短标题（可选，30 字内）" />
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="form.desc" type="textarea" :rows="3" placeholder="正文简介（可选）" />
        </el-form-item>
        <el-form-item label="话题">
          <el-input v-model="form.topics" placeholder="逗号分隔，如：收纳,好物分享" />
        </el-form-item>
        <el-form-item label="谁可以看">
          <el-radio-group v-model="form.visibility">
            <el-radio value="public">公开</el-radio>
            <el-radio value="friends">好友可见</el-radio>
            <el-radio value="private">仅自己可见</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="允许保存">
          <el-switch v-model="form.allow_save" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button :loading="creating" @click="submitCreate(false)">存草稿</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate(true)">立即发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>
