<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { xhsApi, type XhsJob, type XhsLoginStatus } from "@/api/xhs";

// ---- 凭证 ----
const loginStatus = ref<XhsLoginStatus | null>(null);
const checking = ref(false);

async function loadStatus() {
  checking.value = true;
  try {
    loginStatus.value = await xhsApi.loginStatus();
  } finally {
    checking.value = false;
  }
}

// 扫码登录
const qrVisible = ref(false);
const qrImage = ref("");
const qrStatus = ref("");
let qrTimer: ReturnType<typeof setInterval> | null = null;

function stopQrPolling() {
  if (qrTimer) {
    clearInterval(qrTimer);
    qrTimer = null;
  }
}

async function startQrLogin() {
  try {
    const start = await xhsApi.qrcodeStart();
    qrImage.value = `data:image/png;base64,${start.qr_image_base64}`;
    qrStatus.value = "请用小红书 App 扫码";
    qrVisible.value = true;
    stopQrPolling();
    qrTimer = setInterval(async () => {
      try {
        const poll = await xhsApi.qrcodePoll(start.session_id);
        qrStatus.value = poll.message || poll.status;
        if (poll.logged_in) {
          stopQrPolling();
          ElMessage.success("扫码登录成功");
          qrVisible.value = false;
          await loadStatus();
        } else if (poll.status === "expired" || poll.status === "error") {
          stopQrPolling();
          qrStatus.value += "，请重新发起扫码";
        }
      } catch {
        // 瞬时错误不打断轮询
      }
    }, 2500);
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "二维码获取失败");
  }
}

// 短信登录
const smsVisible = ref(false);
const smsPhone = ref("");
const smsCode = ref("");
const smsSession = ref("");
const smsSending = ref(false);
const smsVerifying = ref(false);

async function sendSmsCode() {
  if (!smsPhone.value.trim()) {
    ElMessage.warning("请输入手机号");
    return;
  }
  smsSending.value = true;
  try {
    const result = await xhsApi.phoneSend(smsPhone.value.trim());
    smsSession.value = result.session_id;
    ElMessage.success(result.message || "验证码已发送");
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "验证码发送失败");
  } finally {
    smsSending.value = false;
  }
}

async function verifySmsCode() {
  if (!smsCode.value.trim() || !smsSession.value) {
    ElMessage.warning("请先获取验证码并输入");
    return;
  }
  smsVerifying.value = true;
  try {
    const status = await xhsApi.phoneVerify(smsSession.value, smsCode.value.trim());
    if (status.logged_in) {
      ElMessage.success("登录成功");
      smsVisible.value = false;
      smsCode.value = "";
      await loadStatus();
    } else {
      ElMessage.error(status.message || "验证失败");
    }
  } finally {
    smsVerifying.value = false;
  }
}

// Cookie 粘贴
const cookieVisible = ref(false);
const cookieInput = ref("");
const cookieSaving = ref(false);

async function saveCookie() {
  if (!cookieInput.value.trim()) {
    ElMessage.warning("请粘贴 Cookie");
    return;
  }
  cookieSaving.value = true;
  try {
    const status = await xhsApi.loginCookie(cookieInput.value.trim());
    if (status.logged_in) {
      ElMessage.success("Cookie 登录成功");
      cookieVisible.value = false;
      cookieInput.value = "";
      await loadStatus();
    } else {
      ElMessage.error(status.message || "Cookie 无效");
    }
  } finally {
    cookieSaving.value = false;
  }
}

// ---- 抓取 ----
const activeTab = ref("search");
const searchKeyword = ref("");
const searchLoading = ref(false);
const notes = ref<Record<string, unknown>[]>([]);
const notesError = ref("");

function pickNoteFields(item: Record<string, unknown>) {
  const interact = (item.interact_info || {}) as Record<string, unknown>;
  const user = (item.user || {}) as Record<string, unknown>;
  const cover = item.cover as Record<string, unknown> | string | undefined;
  const coverUrl =
    typeof cover === "string" ? cover : ((cover?.url as string) || (cover?.info_list as Array<{ url?: string }> | undefined)?.[0]?.url || "");
  return {
    note_id: (item.note_id || item.id || "") as string,
    title: ((item.display_title || item.title || item.name || "(无标题)") as string),
    author: ((user.nickname || user.name || item.nickname || "-") as string),
    liked: String(interact.liked_count ?? item.liked_count ?? "-"),
    xsec: (item.xsec_token || "") as string,
    cover: coverUrl,
    raw: item,
  };
}

async function doSearch() {
  if (!searchKeyword.value.trim()) {
    ElMessage.warning("请输入搜索关键词");
    return;
  }
  searchLoading.value = true;
  notesError.value = "";
  try {
    const response = await xhsApi.search(searchKeyword.value.trim(), 20);
    const data = response.data;
    const list = Array.isArray(data) ? data : ((data as Record<string, unknown>)?.items || (data as Record<string, unknown>)?.notes || []);
    notes.value = (list as Record<string, unknown>[]) || [];
    if (!notes.value.length) notesError.value = response.message || "无结果";
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    notesError.value = detail || "搜索失败";
  } finally {
    searchLoading.value = false;
  }
}

// 笔记详情
const detailInput = ref("");
const detailLoading = ref(false);
const detailData = ref<Record<string, unknown> | null>(null);
const detailError = ref("");

async function fetchDetail() {
  if (!detailInput.value.trim()) {
    ElMessage.warning("请粘贴笔记链接或 ID");
    return;
  }
  detailLoading.value = true;
  detailError.value = "";
  try {
    const response = await xhsApi.noteDetail(detailInput.value.trim());
    detailData.value = (response.data as Record<string, unknown>) || null;
    if (!response.success) detailError.value = response.message;
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    detailError.value = detail || "获取失败";
  } finally {
    detailLoading.value = false;
  }
}

// 结果抽屉
const drawerVisible = ref(false);
const drawerTitle = ref("详情");
const drawerData = ref<Record<string, unknown> | null>(null);

function openDetail(item: Record<string, unknown>) {
  const fields = pickNoteFields(item);
  drawerTitle.value = fields.title;
  drawerData.value = item;
  drawerVisible.value = true;
}

// 下载/导出任务
const jobs = ref<XhsJob[]>([]);
const jobsLoading = ref(false);

async function loadJobs() {
  jobsLoading.value = true;
  try {
    jobs.value = await xhsApi.listJobs();
  } finally {
    jobsLoading.value = false;
  }
}

function artifactUrl(jobId: string, path: string) {
  const token = localStorage.getItem("flowpulse_token") || "";
  const base = import.meta.env.VITE_API_BASE_URL || "/api";
  return `${base}/v1/xhs/jobs/${jobId}/artifacts/${path}?token=${encodeURIComponent(token)}`;
}

function fmtTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

onMounted(async () => {
  await Promise.all([loadStatus(), loadJobs()]);
});

onBeforeUnmount(stopQrPolling);
</script>

<template>
  <div class="space-y-4">
    <!-- 凭证卡 -->
    <el-card shadow="never">
      <template #header>
        <div class="flex items-center justify-between">
          <span class="font-bold">小红书登录</span>
          <el-tag :type="loginStatus?.logged_in ? 'success' : 'info'" round>
            {{ loginStatus?.logged_in ? `已登录${loginStatus.user_id ? " · " + loginStatus.user_id : ""}` : "未登录" }}
          </el-tag>
        </div>
      </template>
      <div class="flex flex-wrap gap-2">
        <el-button type="primary" @click="startQrLogin">扫码登录</el-button>
        <el-button @click="smsVisible = true">短信登录</el-button>
        <el-button plain @click="cookieVisible = true">粘贴 Cookie</el-button>
        <el-button :loading="checking" @click="loadStatus">重新检测</el-button>
      </div>
      <div v-if="loginStatus?.message && !loginStatus.logged_in" class="mt-2 text-xs text-gray-400">
        {{ loginStatus.message }}
      </div>
    </el-card>

    <!-- 抓取功能卡 -->
    <el-card shadow="never">
      <template #header><span class="font-bold">数据抓取</span></template>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="搜索笔记" name="search">
          <div class="flex gap-2">
            <el-input
              v-model="searchKeyword"
              placeholder="输入关键词搜索小红书笔记"
              clearable
              @keyup.enter="doSearch"
            />
            <el-button type="primary" :loading="searchLoading" @click="doSearch">搜索</el-button>
          </div>
          <el-alert v-if="notesError" class="mt-3" type="warning" :title="notesError" :closable="false" />
          <el-table v-if="notes.length" :data="notes" class="mt-3">
            <el-table-column label="封面" width="80">
              <template #default="{ row }">
                <el-image
                  v-if="pickNoteFields(row).cover"
                  :src="pickNoteFields(row).cover"
                  :preview-src-list="[pickNoteFields(row).cover]"
                  fit="cover"
                  style="width: 56px; height: 56px; border-radius: 6px"
                  referrerpolicy="no-referrer"
                />
              </template>
            </el-table-column>
            <el-table-column label="标题" min-width="240">
              <template #default="{ row }">
                <el-link type="primary" @click="openDetail(row)">{{ pickNoteFields(row).title }}</el-link>
              </template>
            </el-table-column>
            <el-table-column label="作者" width="140">
              <template #default="{ row }">{{ pickNoteFields(row).author }}</template>
            </el-table-column>
            <el-table-column label="点赞" width="100" align="center">
              <template #default="{ row }">{{ pickNoteFields(row).liked }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="笔记详情" name="detail">
          <div class="flex gap-2">
            <el-input v-model="detailInput" placeholder="粘贴小红书笔记链接（explore/discovery/item）" clearable @keyup.enter="fetchDetail" />
            <el-button type="primary" :loading="detailLoading" @click="fetchDetail">获取</el-button>
          </div>
          <el-alert v-if="detailError" class="mt-3" type="error" :title="detailError" :closable="false" />
          <pre v-if="detailData" class="json-view">{{ JSON.stringify(detailData, null, 2) }}</pre>
        </el-tab-pane>

        <el-tab-pane :label="`下载 / 导出（${jobs.length}）`" name="jobs">
          <div class="mb-2 flex justify-end">
            <el-button size="small" :loading="jobsLoading" @click="loadJobs">刷新</el-button>
          </div>
          <el-table v-if="jobs.length" :data="jobs">
            <el-table-column prop="id" label="任务" width="130">
              <template #default="{ row }">{{ row.id.slice(0, 8) }}</template>
            </el-table-column>
            <el-table-column prop="type" label="类型" width="90" />
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'completed' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="note_count" label="笔记数" width="80" align="center" />
            <el-table-column label="创建时间" width="160">
              <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="产物" min-width="200">
              <template #default="{ row }">
                <el-link
                  v-for="a in row.artifacts"
                  :key="a"
                  class="mr-2"
                  type="primary"
                  :href="artifactUrl(row.id, a)"
                  target="_blank"
                >{{ a }}</el-link>
                <span v-if="!row.artifacts?.length" class="text-gray-400 text-xs">{{ row.message || row.error || "-" }}</span>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="还没有下载/导出任务" :image-size="60" />
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 结果抽屉 -->
    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="520px">
      <pre class="json-view">{{ JSON.stringify(drawerData, null, 2) }}</pre>
    </el-drawer>

    <!-- 扫码登录 -->
    <el-dialog v-model="qrVisible" title="小红书 · 扫码登录" width="360px" @close="stopQrPolling">
      <div class="flex flex-col items-center gap-3">
        <img v-if="qrImage" :src="qrImage" alt="登录二维码" style="width: 240px; height: 240px" />
        <div class="text-sm text-gray-500">{{ qrStatus }}</div>
        <el-button size="small" @click="startQrLogin">刷新二维码</el-button>
      </div>
    </el-dialog>

    <!-- 短信登录 -->
    <el-dialog v-model="smsVisible" title="小红书 · 短信登录" width="420px">
      <div class="space-y-3">
        <el-input v-model="smsPhone" placeholder="手机号" clearable>
          <template #prepend>+86</template>
        </el-input>
        <el-button class="w-full" :loading="smsSending" @click="sendSmsCode">发送验证码</el-button>
        <el-input v-model="smsCode" placeholder="输入收到的验证码" clearable @keyup.enter="verifySmsCode" />
        <el-button class="w-full" type="primary" :loading="smsVerifying" @click="verifySmsCode">验证并登录</el-button>
      </div>
    </el-dialog>

    <!-- Cookie 粘贴 -->
    <el-dialog v-model="cookieVisible" title="小红书 · 粘贴 Cookie" width="560px">
      <el-alert type="info" :closable="false" class="mb-3">
        浏览器登录 xiaohongshu.com → F12 → Network → 任选请求 → Request Headers 复制完整 Cookie。
      </el-alert>
      <el-input v-model="cookieInput" type="textarea" :rows="5" placeholder="a1=...; web_session=...;（完整一串）" />
      <template #footer>
        <el-button @click="cookieVisible = false">取消</el-button>
        <el-button type="primary" :loading="cookieSaving" @click="saveCookie">保存并登录</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.json-view {
  margin-top: 12px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.7;
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
