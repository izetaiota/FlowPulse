<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { monitorApi, type XhsContent, type XhsMonitor } from "@/api/monitor";

const monitors = ref<XhsMonitor[]>([]);
const scheduler = ref<{ enabled: boolean; task_alive: boolean; due_now: number } | null>(null);
const loading = ref(false);
const scanningIds = ref<number[]>([]);

const contents = ref<XhsContent[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const contentMonitor = ref<number | null>(null);
const contentsLoading = ref(false);

const monitorOptions = computed(() => [
  { value: null as number | null, label: "全部来源" },
  ...monitors.value.map((m) => ({ value: m.id, label: m.name || m.target })),
]);

async function loadMonitors() {
  loading.value = true;
  try {
    const [list, status] = await Promise.all([monitorApi.list(), monitorApi.status()]);
    monitors.value = list.monitors;
    scheduler.value = status;
  } catch {
    ElMessage.error("监控目标加载失败");
  } finally {
    loading.value = false;
  }
}

async function loadContents() {
  contentsLoading.value = true;
  try {
    const result = await monitorApi.contents({
      monitor_id: contentMonitor.value ?? undefined,
      page: page.value,
      page_size: pageSize.value,
    });
    contents.value = result.contents;
    total.value = result.total;
  } catch {
    ElMessage.error("作品记录加载失败");
  } finally {
    contentsLoading.value = false;
  }
}

async function refreshAll() {
  await Promise.all([loadMonitors(), loadContents()]);
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
}

// ---- 新增监控 ----
const createVisible = ref(false);
const creating = ref(false);
const form = ref({
  kind: "keyword" as "creator" | "keyword",
  target: "",
  name: "",
  interval_minutes: 30,
  include_keywords: "",
  exclude_keywords: "",
  backfill_count: 10,
});

function openCreate() {
  form.value = {
    kind: "keyword",
    target: "",
    name: "",
    interval_minutes: 30,
    include_keywords: "",
    exclude_keywords: "",
    backfill_count: 10,
  };
  createVisible.value = true;
}

async function submitCreate() {
  const target = form.value.target.trim();
  if (!target) {
    ElMessage.warning(form.value.kind === "creator" ? "请粘贴用户主页链接" : "请输入关键词");
    return;
  }
  creating.value = true;
  try {
    await monitorApi.create({ ...form.value, target });
    ElMessage.success("监控目标已创建，首次扫描将只入库基线不推送");
    createVisible.value = false;
    await refreshAll();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "创建失败");
  } finally {
    creating.value = false;
  }
}

// ---- 行操作 ----
async function scanNow(monitor: XhsMonitor) {
  scanningIds.value.push(monitor.id);
  try {
    const { result } = await monitorApi.scan(monitor.id);
    if (result.ok) {
      ElMessage.success(`扫描完成：新作品 ${result.new_count} 篇${result.notified ? "（已推送通知）" : ""}`);
    } else {
      ElMessage.warning(`扫描失败：${result.message}`);
    }
    await refreshAll();
  } catch {
    ElMessage.error("扫描请求失败");
  } finally {
    scanningIds.value = scanningIds.value.filter((id) => id !== monitor.id);
  }
}

async function toggleStatus(monitor: XhsMonitor) {
  const next = monitor.status === "active" ? "paused" : "active";
  try {
    await monitorApi.update(monitor.id, { status: next });
    ElMessage.success(next === "active" ? "已恢复" : "已暂停");
    await loadMonitors();
  } catch {
    ElMessage.error("操作失败");
  }
}

async function removeMonitor(monitor: XhsMonitor) {
  try {
    await ElMessageBox.confirm(
      `删除「${monitor.name || monitor.target}」及其已收录的 ${monitor.content_count} 条作品记录？`,
      "删除监控",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    await monitorApi.remove(monitor.id);
    ElMessage.success("已删除");
    if (contentMonitor.value === monitor.id) contentMonitor.value = null;
    page.value = 1;
    await refreshAll();
  } catch {
    ElMessage.error("删除失败");
  }
}

function scanStatusTag(status: string): { label: string; type: "success" | "danger" | "info" } {
  if (status === "ok") return { label: "正常", type: "success" };
  if (status === "error") return { label: "出错", type: "danger" };
  return { label: "未扫描", type: "info" };
}

onMounted(refreshAll);
</script>

<template>
  <div class="space-y-4">
    <!-- 监控目标 -->
    <el-card shadow="never" v-loading="loading">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span class="font-bold">作品监控目标</span>
            <span v-if="scheduler" class="ml-3 text-xs text-slate-400">
              调度{{ scheduler.enabled ? "已启用" : "已关闭" }}
              <template v-if="scheduler.task_alive"> · 运行中</template>
              · 到期 {{ scheduler.due_now }} 个
            </span>
          </div>
          <div class="flex gap-2">
            <el-button @click="refreshAll">刷新</el-button>
            <el-button type="primary" @click="openCreate">新增监控</el-button>
          </div>
        </div>
      </template>

      <el-table :data="monitors">
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="row.kind === 'creator' ? 'warning' : 'primary'" size="small">
              {{ row.kind === "creator" ? "创作者" : "关键词" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="130" show-overflow-tooltip />
        <el-table-column prop="target" label="目标" min-width="180" show-overflow-tooltip />
        <el-table-column label="周期" width="90">
          <template #default="{ row }">{{ row.interval_minutes }} 分钟</template>
        </el-table-column>
        <el-table-column prop="content_count" label="作品数" width="80" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
              {{ row.status === "active" ? "监控中" : "已暂停" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近扫描" min-width="150">
          <template #default="{ row }">
            {{ formatTime(row.last_scan_at) }}
            <el-tag size="small" :type="scanStatusTag(row.last_scan_status).type" class="ml-1">
              {{ scanStatusTag(row.last_scan_status).label }}
            </el-tag>
            <el-tooltip v-if="row.last_error" :content="row.last_error" placement="top">
              <el-icon class="ml-1 align-middle text-slate-400"><WarningFilled /></el-icon>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              :loading="scanningIds.includes(row.id)"
              @click="scanNow(row)"
            >
              扫描
            </el-button>
            <el-button size="small" @click="toggleStatus(row)">
              {{ row.status === "active" ? "暂停" : "恢复" }}
            </el-button>
            <el-button size="small" type="danger" plain @click="removeMonitor(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无监控目标：新增后自动定时扫描小红书新作品并推送通知" />
        </template>
      </el-table>
    </el-card>

    <!-- 作品记录 -->
    <el-card shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <span class="font-bold">作品记录（{{ total }}）</span>
          <el-select
            v-model="contentMonitor"
            style="width: 200px"
            @change="
              page = 1;
              loadContents();
            "
          >
            <el-option
              v-for="opt in monitorOptions"
              :key="String(opt.value)"
              :label="opt.label"
              :value="opt.value ?? undefined"
            />
          </el-select>
        </div>
      </template>

      <el-table :data="contents" v-loading="contentsLoading">
        <el-table-column label="标题" min-width="240">
          <template #default="{ row }">
            <a :href="row.url" target="_blank" rel="noopener" class="fp-note-link">
              {{ row.title || row.note_id }}
            </a>
          </template>
        </el-table-column>
        <el-table-column prop="author" label="作者" min-width="110" show-overflow-tooltip />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.note_type === 'video' ? 'danger' : 'info'">
              {{ row.note_type === "video" ? "视频" : "图文" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="liked_count" label="点赞" width="90" />
        <el-table-column prop="monitor_name" label="来源监控" min-width="110" show-overflow-tooltip />
        <el-table-column label="发现时间" width="160">
          <template #default="{ row }">{{ formatTime(row.first_seen_at) }}</template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无作品记录" />
        </template>
      </el-table>

      <div class="mt-3 flex justify-end">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadContents"
        />
      </div>
    </el-card>

    <!-- 新增监控弹窗 -->
    <el-dialog v-model="createVisible" title="新增作品监控" width="520px">
      <el-form label-width="110px">
        <el-form-item label="监控类型">
          <el-radio-group v-model="form.kind">
            <el-radio value="keyword">关键词搜索</el-radio>
            <el-radio value="creator">创作者主页</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="form.kind === 'creator' ? '主页链接' : '关键词'">
          <el-input
            v-model="form.target"
            :placeholder="
              form.kind === 'creator'
                ? 'https://www.xiaohongshu.com/user/profile/xxx?xsec_token=...'
                : '如：收纳教程'
            "
          />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="备注名（可选）" />
        </el-form-item>
        <el-form-item label="扫描周期">
          <el-input-number v-model="form.interval_minutes" :min="1" :max="1440" />
          <span class="ml-2 text-xs text-slate-400">分钟（1~1440，不建议低于 15）</span>
        </el-form-item>
        <el-form-item label="首扫基线">
          <el-input-number v-model="form.backfill_count" :min="0" :max="100" />
          <span class="ml-2 text-xs text-slate-400">首次扫描入库条数（不推送通知）</span>
        </el-form-item>
        <el-form-item label="包含关键词">
          <el-input v-model="form.include_keywords" placeholder="标题需命中其一，留空全收" />
        </el-form-item>
        <el-form-item label="排除关键词">
          <el-input v-model="form.exclude_keywords" placeholder="标题命中即跳过，逗号分隔" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.fp-note-link {
  color: var(--el-color-primary);
  text-decoration: none;
}

.fp-note-link:hover {
  text-decoration: underline;
}
</style>
