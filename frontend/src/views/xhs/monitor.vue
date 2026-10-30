<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { monitorApi, type XhsMonitor } from "@/api/monitor";
import { douyinAccountApi, douyinMonitorApi, type DouyinAccountStatus, type DouyinMonitor } from "@/api/douyin";
import { ksAccountApi, ksMonitorApi, type KsAccountStatus } from "@/api/ks";

// 平台维度：xhs / douyin 共用本页
type Platform = "xhs" | "douyin" | "ks";
type AnyMonitor = (XhsMonitor | DouyinMonitor) & { platform: Platform };

const platform = ref<Platform | "">("");
const monitors = ref<AnyMonitor[]>([]);
const loading = ref(false);
const scanningIds = ref<number[]>([]);

async function loadMonitors() {
  loading.value = true;
  try {
    const tasks: Promise<void>[] = [];
    if (platform.value === "" || platform.value === "xhs") {
      tasks.push(
        monitorApi.list().then((r) => {
          monitors.value = [
            ...monitors.value.filter((m) => m.platform !== "xhs"),
            ...r.monitors.map((m) => ({ ...m, platform: "xhs" as Platform })),
          ];
        }),
      );
    }
    if (platform.value === "" || platform.value === "douyin") {
      tasks.push(
        douyinMonitorApi.list().then((r) => {
          monitors.value = [
            ...monitors.value.filter((m) => m.platform !== "douyin"),
            ...r.monitors.map((m) => ({ ...m, platform: "douyin" as Platform })),
          ];
        }),
      );
    }
    if (platform.value === "" || platform.value === "ks") {
      tasks.push(
        ksMonitorApi.list().then((r) => {
          monitors.value = [
            ...monitors.value.filter((m) => m.platform !== "ks"),
            ...r.monitors.map((m) => ({ ...m, platform: "ks" as Platform })),
          ];
        }),
      );
    }
    monitors.value = [];
    await Promise.all(tasks);
  } catch {
    ElMessage.error("监控目标加载失败");
  } finally {
    loading.value = false;
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
}

function scanStatusTag(status: string): { label: string; type: "success" | "danger" | "info" } {
  if (status === "ok") return { label: "正常", type: "success" };
  if (status === "error") return { label: "出错", type: "danger" };
  return { label: "未扫描", type: "info" };
}

// ---- 行操作（按平台路由 API） ----
const api = (p: Platform) => (p === "xhs" ? monitorApi : p === "douyin" ? douyinMonitorApi : ksMonitorApi);

async function scanNow(monitor: AnyMonitor) {
  scanningIds.value.push(monitor.id);
  try {
    const { result } = await api(monitor.platform).scan(monitor.id);
    if (result.ok) {
      ElMessage.success(`扫描完成：新作品 ${result.new_count} 条${result.notified ? "（已推送通知）" : ""}`);
    } else {
      ElMessage.warning(`扫描失败：${result.message}`);
    }
    await Promise.all([loadMonitors(), loadContents()]);
  } catch {
    ElMessage.error("扫描请求失败");
  } finally {
    scanningIds.value = scanningIds.value.filter((id) => id !== monitor.id);
  }
}

async function toggleStatus(monitor: AnyMonitor) {
  const next = monitor.status === "active" ? "paused" : "active";
  try {
    await api(monitor.platform).update(monitor.id, { status: next });
    ElMessage.success(next === "active" ? "已恢复" : "已暂停");
    await loadMonitors();
  } catch {
    ElMessage.error("操作失败");
  }
}

async function removeMonitor(monitor: AnyMonitor) {
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
    await api(monitor.platform).remove(monitor.id);
    ElMessage.success("已删除");
    if (contentMonitor.value === monitor.id) contentMonitor.value = null;
    await Promise.all([loadMonitors(), loadContents()]);
  } catch {
    ElMessage.error("删除失败");
  }
}

// ---- 新增监控 ----
const createVisible = ref(false);
const creating = ref(false);
const form = ref({
  platform: "xhs" as Platform,
  kind: "keyword" as "creator" | "keyword",
  target: "",
  name: "",
  interval_minutes: 30,
  include_keywords: "",
  exclude_keywords: "",
  backfill_count: 10,
});

function openCreate(platform: Platform = "xhs") {
  form.value = {
    platform,
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
    ElMessage.warning(form.value.kind === "creator" ? "请填写主页链接或 sec_uid" : "请输入关键词");
    return;
  }
  creating.value = true;
  try {
    await api(form.value.platform).create({ ...form.value, target });
    ElMessage.success("监控目标已创建，首次扫描将只入库基线不推送");
    createVisible.value = false;
    await Promise.all([loadMonitors(), loadContents()]);
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "创建失败");
  } finally {
    creating.value = false;
  }
}

// ---- 抖音账号（T3.1） ----
const douyinAccount = ref<DouyinAccountStatus | null>(null);
const cookieVisible = ref(false);
const cookieInput = ref("");
const cookieSaving = ref(false);
const qrState = ref("");
const qrMessage = ref("");
const qrPolling = ref<number | null>(null);

async function loadDouyinAccount() {
  try {
    douyinAccount.value = await douyinAccountApi.status();
  } catch {
    douyinAccount.value = null;
  }
}

async function importCookie() {
  if (!cookieInput.value.trim()) {
    ElMessage.warning("请粘贴抖音 Cookie（需含 sessionid 与 ttwid）");
    return;
  }
  cookieSaving.value = true;
  try {
    await douyinAccountApi.importCookie(cookieInput.value.trim());
    ElMessage.success("Cookie 已导入");
    cookieVisible.value = false;
    cookieInput.value = "";
    await loadDouyinAccount();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "导入失败");
  } finally {
    cookieSaving.value = false;
  }
}

async function startQrLogin() {
  try {
    const started = await douyinAccountApi.qrStart();
    qrState.value = started.state;
    qrMessage.value = started.message;
    ElMessage.info("已在本机打开浏览器，请在页面中扫码登录抖音");
    if (qrPolling.value) window.clearInterval(qrPolling.value);
    qrPolling.value = window.setInterval(async () => {
      const state = await douyinAccountApi.qrPoll(started.session_id);
      qrState.value = state.state;
      qrMessage.value = state.message;
      if (state.state === "logged_in") {
        stopQrPolling();
        ElMessage.success("扫码登录成功，账号已保存");
        await loadDouyinAccount();
      } else if (["expired", "failed", "unknown"].includes(state.state)) {
        stopQrPolling();
      }
    }, 3000);
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "无法启动扫码（未安装浏览器引擎？）");
  }
}

function stopQrPolling() {
  if (qrPolling.value) {
    window.clearInterval(qrPolling.value);
    qrPolling.value = null;
  }
}

async function clearDouyinAccount() {
  try {
    await ElMessageBox.confirm("删除抖音账号（Cookie 与登录态）？", "删除账号", {
      type: "warning",
    });
  } catch {
    return;
  }
  await douyinAccountApi.clear();
  ElMessage.success("已删除");
  await loadDouyinAccount();
}


// ---- 快手账号（T5.1） ----
const ksAccount = ref<KsAccountStatus | null>(null);
const ksCookieVisible = ref(false);
const ksCookieInput = ref("");
const ksCookieSaving = ref(false);
const ksQrMessage = ref("");
const ksQrPolling = ref<number | null>(null);

async function loadKsAccount() {
  try {
    ksAccount.value = await ksAccountApi.status();
  } catch {
    ksAccount.value = null;
  }
}

async function importKsCookie() {
  if (!ksCookieInput.value.trim()) {
    ElMessage.warning("请粘贴快手 Cookie（需含 userId 与 passToken）");
    return;
  }
  ksCookieSaving.value = true;
  try {
    await ksAccountApi.importCookie(ksCookieInput.value.trim());
    ElMessage.success("Cookie 已导入");
    ksCookieVisible.value = false;
    ksCookieInput.value = "";
    await loadKsAccount();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "导入失败");
  } finally {
    ksCookieSaving.value = false;
  }
}

async function startKsQrLogin() {
  try {
    const started = await ksAccountApi.qrStart();
    ksQrMessage.value = started.message;
    ElMessage.info("已在本机打开浏览器，请在页面中登录快手");
    if (ksQrPolling.value) window.clearInterval(ksQrPolling.value);
    ksQrPolling.value = window.setInterval(async () => {
      const state = await ksAccountApi.qrPoll(started.session_id);
      ksQrMessage.value = state.message;
      if (state.state === "logged_in") {
        stopKsQrPolling();
        ElMessage.success("登录成功，账号已保存");
        await loadKsAccount();
      } else if (["expired", "failed", "unknown"].includes(state.state)) {
        stopKsQrPolling();
      }
    }, 3000);
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "无法启动扫码（未安装浏览器引擎？）");
  }
}

function stopKsQrPolling() {
  if (ksQrPolling.value) {
    window.clearInterval(ksQrPolling.value);
    ksQrPolling.value = null;
  }
}

async function clearKsAccount() {
  try {
    await ElMessageBox.confirm("删除快手账号（Cookie 与登录态）？", "删除账号", { type: "warning" });
  } catch {
    return;
  }
  await ksAccountApi.clear();
  ElMessage.success("已删除");
  await loadKsAccount();
}

// ---- 作品记录（跨平台合并） ----
const contents = ref<Record<string, unknown>[]>([]);
const contentMonitor = ref<number | null>(null);
const contentsLoading = ref(false);

const monitorOptions = computed(() => [
  { value: null as number | null, label: "全部来源" },
  ...monitors.value.map((m) => ({ value: m.id, label: `[${m.platform === "xhs" ? "小红书" : "抖音"}] ${m.name || m.target}` })),
]);

async function loadContents() {
  contentsLoading.value = true;
  try {
    const requests: Promise<Record<string, unknown>[]>[] = [];
    if (platform.value === "" || platform.value === "xhs") {
      requests.push(
        monitorApi
          .contents({ monitor_id: contentMonitor.value ?? undefined, page: 1, page_size: 100 })
          .then((r) => r.contents.map((c) => ({ ...c, platform: "xhs" }))),
      );
    }
    if (platform.value === "" || platform.value === "douyin") {
      requests.push(
        douyinMonitorApi
          .contents({ monitor_id: contentMonitor.value ?? undefined, page: 1, page_size: 100 })
          .then((r) => r.contents.map((c) => ({ ...c, platform: "douyin" }))),
      );
    }
    if (platform.value === "" || platform.value === "ks") {
      requests.push(
        ksMonitorApi
          .contents({ monitor_id: contentMonitor.value ?? undefined, page: 1, page_size: 100 })
          .then((r) => r.contents.map((c) => ({ ...c, platform: "ks" }))),
      );
    }
    const merged = (await Promise.all(requests)).flat();
    merged.sort((a, b) => String(b.first_seen_at ?? "").localeCompare(String(a.first_seen_at ?? "")));
    contents.value = merged.slice(0, 100);
  } catch {
    ElMessage.error("作品记录加载失败");
  } finally {
    contentsLoading.value = false;
  }
}

async function refreshAll() {
  await Promise.all([loadMonitors(), loadContents(), loadDouyinAccount(), loadKsAccount()]);
}

onMounted(refreshAll);
onUnmounted(() => {
  stopQrPolling();
  stopKsQrPolling();
});
</script>

<template>
  <div class="space-y-4">
    <!-- 抖音账号 -->
    <el-card v-if="platform === '' || platform === 'douyin'" shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span class="font-bold">抖音账号</span>
            <span class="ml-3 text-xs text-slate-400">
              {{ douyinAccount?.configured
                ? douyinAccount.logged_in_guess ? "已配置 Cookie" : "Cookie 不完整"
                : "未配置（监控扫描将无法读取）" }}
              · 引擎 {{ douyinAccount?.engine || "检测中" }}
            </span>
          </div>
          <div class="flex gap-2">
            <el-button size="small" @click="cookieVisible = true">粘贴 Cookie</el-button>
            <el-button size="small" type="primary" @click="startQrLogin">浏览器扫码</el-button>
            <el-button v-if="douyinAccount?.configured" size="small" type="danger" plain @click="clearDouyinAccount">
              删除
            </el-button>
          </div>
        </div>
      </template>
      <p v-if="qrMessage" class="m-0 text-xs" :class="qrState === 'logged_in' ? 'text-emerald-600' : 'text-slate-500'">
        {{ qrMessage }}
      </p>
    </el-card>

    <!-- 快手账号 -->
    <el-card v-if="platform === '' || platform === 'ks'" shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span class="font-bold">快手账号</span>
            <span class="ml-3 text-xs text-slate-400">
              {{ ksAccount?.configured
                ? ksAccount.logged_in_guess ? "已配置 Cookie" : "Cookie 不完整"
                : "未配置（监控扫描将无法读取）" }}
              · 引擎 {{ ksAccount?.engine || "检测中" }}
            </span>
          </div>
          <div class="flex gap-2">
            <el-button size="small" @click="ksCookieVisible = true">粘贴 Cookie</el-button>
            <el-button size="small" type="primary" @click="startKsQrLogin">浏览器扫码</el-button>
            <el-button v-if="ksAccount?.configured" size="small" type="danger" plain @click="clearKsAccount">
              删除
            </el-button>
          </div>
        </div>
      </template>
      <p v-if="qrMessage" class="m-0 text-xs" :class="qrState === 'logged_in' ? 'text-emerald-600' : 'text-slate-500'">
        {{ qrMessage }}
      </p>
    </el-card>

    <!-- 监控目标 -->
    <el-card shadow="never" v-loading="loading">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <span class="font-bold">作品监控目标</span>
            <el-radio-group v-model="platform" size="small" @change="refreshAll">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button value="xhs">小红书</el-radio-button>
              <el-radio-button value="douyin">抖音</el-radio-button>
              <el-radio-button value="ks">快手</el-radio-button>
            </el-radio-group>
          </div>
          <div class="flex gap-2">
            <el-button size="small" @click="refreshAll">刷新</el-button>
            <el-button size="small" type="primary" @click="openCreate()">新增监控</el-button>
          </div>
        </div>
      </template>

      <el-table :data="monitors">
        <el-table-column label="平台" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.platform === 'xhs' ? 'danger' : 'primary'" effect="plain">
              {{ row.platform === "xhs" ? "小红书" : row.platform === "douyin" ? "抖音" : "快手" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="row.kind === 'creator' ? 'warning' : 'primary'" size="small">
              {{ row.kind === "creator" ? "创作者" : "关键词" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="120" show-overflow-tooltip />
        <el-table-column prop="target" label="目标" min-width="170" show-overflow-tooltip />
        <el-table-column label="周期" width="85">
          <template #default="{ row }">{{ row.interval_minutes }} 分钟</template>
        </el-table-column>
        <el-table-column prop="content_count" label="作品数" width="75" />
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
            <el-button size="small" :loading="scanningIds.includes(row.id)" @click="scanNow(row)">
              扫描
            </el-button>
            <el-button size="small" @click="toggleStatus(row)">
              {{ row.status === "active" ? "暂停" : "恢复" }}
            </el-button>
            <el-button size="small" type="danger" plain @click="removeMonitor(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无监控目标：新增后自动定时扫描新作品并推送通知" />
        </template>
      </el-table>
    </el-card>

    <!-- 作品记录 -->
    <el-card shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <span class="font-bold">作品记录（最近 {{ contents.length }} 条）</span>
          <el-select
            v-model="contentMonitor"
            style="width: 260px"
            @change="loadContents"
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
        <el-table-column label="平台" width="85">
          <template #default="{ row }">
            <el-tag size="small" :type="row.platform === 'xhs' ? 'danger' : 'primary'" effect="plain">
              {{ row.platform === "xhs" ? "小红书" : row.platform === "douyin" ? "抖音" : "快手" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标题" min-width="240">
          <template #default="{ row }">
            <a :href="row.url" target="_blank" rel="noopener" class="fp-note-link">
              {{ row.title || row.aweme_id || row.note_id }}
            </a>
          </template>
        </el-table-column>
        <el-table-column prop="author" label="作者" min-width="110" show-overflow-tooltip />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.media_type === 'video' || row.note_type === 'video' ? 'danger' : 'info'">
              {{ row.media_type === "video" || row.note_type === "video" ? "视频" : "图文" }}
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
    </el-card>

    <!-- 新增监控弹窗 -->
    <el-dialog v-model="createVisible" title="新增作品监控" width="540px">
      <el-form label-width="110px">
        <el-form-item label="平台">
          <el-radio-group v-model="form.platform">
            <el-radio value="xhs">小红书</el-radio>
            <el-radio value="douyin">抖音</el-radio>
            <el-radio value="ks">快手</el-radio>
          </el-radio-group>
        </el-form-item>
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
                ? form.platform === 'xhs'
                  ? 'https://www.xiaohongshu.com/user/profile/xxx?xsec_token=...'
                  : form.platform === 'douyin'
                    ? 'https://www.douyin.com/user/MS4Wxxx 或裸 sec_uid'
                    : 'https://www.kuaishou.com/profile/xxx 或裸用户 ID'
                : '如：收纳教程'
            "
          />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="备注名（可选）" />
        </el-form-item>
        <el-form-item label="扫描周期">
          <el-input-number v-model="form.interval_minutes" :min="1" :max="1440" />
          <span class="ml-2 text-xs text-slate-400">分钟（不建议低于 15）</span>
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

    <!-- 快手 Cookie 导入弹窗 -->
    <el-dialog v-model="ksCookieVisible" title="导入快手 Cookie" width="560px">
      <el-input
        v-model="ksCookieInput"
        type="textarea"
        :rows="6"
        placeholder="从已登录快手的浏览器复制完整 Cookie（必须包含 userId 与 passToken）"
      />
      <template #footer>
        <el-button @click="ksCookieVisible = false">取消</el-button>
        <el-button type="primary" :loading="ksCookieSaving" @click="importKsCookie">导入</el-button>
      </template>
    </el-dialog>

    <!-- 抖音 Cookie 导入弹窗 -->
    <el-dialog v-model="cookieVisible" title="导入抖音 Cookie" width="560px">
      <el-input
        v-model="cookieInput"
        type="textarea"
        :rows="6"
        placeholder="从已登录抖音的浏览器复制完整 Cookie（必须包含 sessionid 与 ttwid）"
      />
      <template #footer>
        <el-button @click="cookieVisible = false">取消</el-button>
        <el-button type="primary" :loading="cookieSaving" @click="importCookie">导入</el-button>
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
