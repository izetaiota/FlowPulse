<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  wereadApi,
  type CookieRefreshStatus,
  type QrLoginStatus,
  type SchedulerStatus,
  type WereadArticle,
  type WereadArticleContent,
  type WereadCredential,
  type WereadSubscription,
} from "@/api/weread";

// ---- 凭证 ----
const credential = ref<WereadCredential | null>(null);
const cookieDialogVisible = ref(false);
const cookieInput = ref("");
const savingCookie = ref(false);
const validating = ref(false);

const credentialTag = computed(() => {
  if (!credential.value?.configured) return { text: "未配置", type: "info" as const };
  if (credential.value.valid === true) return { text: "有效", type: "success" as const };
  if (credential.value.valid === false) return { text: "已失效", type: "danger" as const };
  return { text: "待校验", type: "warning" as const };
});

async function loadCredential() {
  credential.value = await wereadApi.getCredential();
}

async function saveCookie() {
  if (!cookieInput.value.trim()) {
    ElMessage.warning("请粘贴微信读书 Cookie");
    return;
  }
  savingCookie.value = true;
  try {
    const result = await wereadApi.saveCredential(cookieInput.value.trim());
    if (result.valid) {
      ElMessage.success(`Cookie 有效（书架 ${result.book_count} 本）`);
    } else {
      ElMessage.warning(`保存成功，但校验未通过：${result.message}`);
    }
    cookieDialogVisible.value = false;
    cookieInput.value = "";
    await loadCredential();
  } finally {
    savingCookie.value = false;
  }
}

async function validateCredential() {
  validating.value = true;
  try {
    const result = await wereadApi.validateCredential();
    if (result.valid) ElMessage.success(result.message);
    else ElMessage.error(result.message);
    await loadCredential();
  } finally {
    validating.value = false;
  }
}

// ---- 扫码登录 ----
const qrDialogVisible = ref(false);
const qrStatus = ref<QrLoginStatus | null>(null);
let qrTimer: ReturnType<typeof setInterval> | null = null;

const qrStateTag = computed(() => {
  const state = qrStatus.value?.state;
  if (state === "success") return { text: "登录成功", type: "success" as const };
  if (state === "failed") return { text: "失败", type: "danger" as const };
  if (state === "cancelled") return { text: "已取消", type: "info" as const };
  if (state === "validating") return { text: "校验中", type: "warning" as const };
  return { text: "等待扫码", type: "warning" as const };
});

function stopQrPolling() {
  if (qrTimer) {
    clearInterval(qrTimer);
    qrTimer = null;
  }
}

async function startQrLogin() {
  qrStatus.value = await wereadApi.startQrLogin();
  qrDialogVisible.value = true;
  stopQrPolling();
  qrTimer = setInterval(pollQrStatus, 2000);
}

async function pollQrStatus() {
  try {
    qrStatus.value = await wereadApi.getQrLoginStatus();
  } catch {
    return; // 瞬时网络错误不打断轮询
  }
  const state = qrStatus.value.state;
  if (state === "success") {
    stopQrPolling();
    ElMessage.success("扫码登录成功，Cookie 已自动保存");
    await loadCredential();
    setTimeout(() => (qrDialogVisible.value = false), 1200);
  } else if (state === "failed" || state === "cancelled") {
    stopQrPolling();
  }
}

async function cancelQrLogin() {
  stopQrPolling();
  await wereadApi.cancelQrLogin();
  qrDialogVisible.value = false;
}

function closeQrDialog() {
  // 用户手动关弹窗：登录会话保留继续跑（浏览器窗口还在），只停轮询
  stopQrPolling();
}

onBeforeUnmount(stopQrPolling);

// ---- Cookie 自动续期 ----
const cookieRefresh = ref<CookieRefreshStatus | null>(null);
const refreshing = ref(false);

async function loadCookieRefresh() {
  cookieRefresh.value = await wereadApi.getCookieRefreshStatus();
}

async function refreshCookieNow() {
  refreshing.value = true;
  try {
    const result = await wereadApi.refreshCookie();
    if (result.ok) {
      ElMessage.success(
        result.changed ? `续期成功，Cookie 已更新（${result.message}）` : `续期成功，Cookie 无变化（${result.message}）`,
      );
    } else if (result.reason === "profile_expired") {
      ElMessage.warning("浏览器登录态已过期，请点击「扫码登录」重新授权");
    } else {
      ElMessage.error(`续期失败：${result.message}`);
    }
    await Promise.all([loadCredential(), loadCookieRefresh()]);
  } finally {
    refreshing.value = false;
  }
}

// ---- 订阅 ----
const subscriptions = ref<WereadSubscription[]>([]);
const subscriptionsError = ref("");
const newSubscriptionInput = ref("");
const adding = ref(false);
const syncing = ref(false);

async function loadSubscriptions() {
  subscriptionsError.value = "";
  try {
    subscriptions.value = await wereadApi.listSubscriptions();
  } catch {
    // 首次加载失败（如后端重启瞬间）不再静默空列表，给出明确重试入口
    subscriptionsError.value = "订阅列表加载失败，请确认后端服务正常后重试。";
  }
}

// ---- 订阅向导：文章链接/名称识别后，引导补充微信读书链接 ----
const wizardVisible = ref(false);
const wizardName = ref("");
const wizardInput = ref("");

function openWizard(name: string) {
  wizardName.value = name;
  wizardInput.value = "";
  wizardVisible.value = true;
}

async function addSubscription() {
  if (!newSubscriptionInput.value.trim()) {
    ElMessage.warning("粘贴公众号文章链接 / 名称 / 微信读书链接均可");
    return;
  }
  adding.value = true;
  try {
    const sub = await wereadApi.addSubscription(newSubscriptionInput.value.trim());
    ElMessage.success(`已订阅：${sub.name || sub.book_id}`);
    newSubscriptionInput.value = "";
    wizardVisible.value = false;
    await loadSubscriptions();
  } catch (error: unknown) {
    const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
    const detail = response?.data?.detail;
    // 已识别公众号但需要补充微信读书链接 → 弹向导
    if (response?.status === 422 && (detail as { code?: string })?.code === "need_weread_link") {
      openWizard((detail as { name?: string }).name || "");
      return;
    }
    const message = typeof detail === "string" ? detail : "订阅失败，请检查输入";
    ElMessage.error({ message, duration: 6000 });
  } finally {
    adding.value = false;
  }
}

async function submitWizard() {
  if (!wizardInput.value.trim()) {
    ElMessage.warning("请粘贴该公众号在微信读书里的链接或 bookId");
    return;
  }
  // 复用主流程：向导输入的是微信读书链接/bookId，正常路径可直接订阅
  newSubscriptionInput.value = wizardInput.value.trim();
  await addSubscription();
}

async function removeSubscription(sub: WereadSubscription) {
  await ElMessageBox.confirm(`确定移除订阅「${sub.name || sub.book_id}」？文章数据将一并删除。`, "移除订阅", {
    type: "warning",
    confirmButtonText: "移除",
    cancelButtonText: "取消",
  });
  await wereadApi.deleteSubscription(sub.book_id);
  ElMessage.success("已移除");
  await loadSubscriptions();
}

async function syncOne(sub: WereadSubscription) {
  const result = await wereadApi.syncOne(sub.book_id);
  if (result.status === "ok") {
    ElMessage.success(`同步完成：新增 ${result.new_articles} 篇${result.message || ""}`);
  } else {
    ElMessage.error(`同步失败：${result.message || result.status}`);
  }
  await loadSubscriptions();
}

async function syncAll() {
  syncing.value = true;
  try {
    const summary = await wereadApi.syncAll();
    ElMessage.success(`同步完成：${summary.ok_count} 成功 / ${summary.error_count} 失败，新增 ${summary.new_articles} 篇`);
    await Promise.all([loadSubscriptions(), loadScheduler()]);
  } finally {
    syncing.value = false;
  }
}

function statusTag(status: string) {
  if (status === "ok") return { text: "正常", type: "success" as const };
  if (status === "auth_error") return { text: "Cookie 失效", type: "danger" as const };
  if (status === "error") return { text: "异常", type: "danger" as const };
  return { text: "未同步", type: "info" as const };
}

// ---- 文章预览 ----
const articlesVisible = ref(false);
const articlesLoading = ref(false);
const articlesError = ref("");
const articles = ref<WereadArticle[]>([]);
const articlesCursor = ref<string | null>(null);
const currentSub = ref<WereadSubscription | null>(null);

async function openArticles(sub: WereadSubscription) {
  currentSub.value = sub;
  articles.value = [];
  articlesCursor.value = null;
  articlesError.value = "";
  articlesVisible.value = true;
  await loadMoreArticles();
}

async function loadMoreArticles() {
  if (!currentSub.value) return;
  articlesLoading.value = true;
  articlesError.value = "";
  try {
    const page = await wereadApi.listArticles(currentSub.value.book_id, 20, articlesCursor.value || undefined);
    articles.value.push(...page.items);
    articlesCursor.value = page.next_cursor;
  } catch {
    // 请求失败时保留已加载内容，明确提示而非伪装成"暂无文章"
    articlesError.value = "文章列表加载失败，请确认后端服务已启动后重试。";
  } finally {
    articlesLoading.value = false;
  }
}

// ---- 站内阅读 ----
const readingArticle = ref<WereadArticle | null>(null);
const readingContent = ref<WereadArticleContent | null>(null);
const readingLoading = ref(false);
const readingError = ref("");

async function openArticle(article: WereadArticle) {
  if (!currentSub.value) return;
  readingArticle.value = article;
  readingContent.value = null;
  readingError.value = "";
  readingLoading.value = true;
  try {
    readingContent.value = await wereadApi.getArticleContent(
      currentSub.value.book_id,
      article.review_id,
    );
    // 后端从原文页读到发布时间后会回填；同步到列表里的同一对象，返回列表即见
    if (readingContent.value.publish_time > 0 && article.publish_time === 0) {
      article.publish_time = readingContent.value.publish_time;
    }
  } catch {
    readingError.value = "正文抓取失败，可能是 Cookie 失效或接口受限，可稍后重试。";
  } finally {
    readingLoading.value = false;
  }
}

function backToList() {
  readingArticle.value = null;
  readingContent.value = null;
  readingError.value = "";
}

// ---- RSS 链接 ----
function rssUrl(bookId?: string) {
  const base = window.location.origin;
  return bookId ? `${base}/api/weread/rss/${bookId}.xml` : `${base}/api/weread/rss/all.xml`;
}

async function copyRss(bookId?: string) {
  await navigator.clipboard.writeText(rssUrl(bookId));
  ElMessage.success("RSS 链接已复制");
}

// ---- 调度器 ----
const scheduler = ref<SchedulerStatus | null>(null);

async function loadScheduler() {
  scheduler.value = await wereadApi.getSchedulerStatus();
}

function fmtTime(value: string | number | null | undefined): string {
  if (!value) return "-";
  if (typeof value === "number") {
    if (value <= 0) return "-";
    return new Date(value * 1000).toLocaleString("zh-CN", { hour12: false });
  }
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

onMounted(async () => {
  await Promise.all([loadCredential(), loadSubscriptions(), loadScheduler(), loadCookieRefresh()]);
});
</script>

<style scoped>
.article-card {
  border: 1px solid #e8eaf0;
  border-radius: 8px;
  padding: 12px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.article-card:hover {
  border-color: #a5b4fc;
}

.reading-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.reading-origin {
  font-size: 13px;
  color: var(--el-color-primary);
}

.reading-title {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.5;
}

.reading-meta {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 16px;
}

.reading-body-wrap {
  min-height: 200px;
}

/* 微信公众号正文排版（v-html 内容需用 :deep） */
.reading-body {
  font-size: 15px;
  line-height: 1.9;
  color: #333;
  word-break: break-word;
}

.reading-body :deep(img) {
  max-width: 100% !important;
  height: auto;
  border-radius: 4px;
}

.reading-body :deep(p) {
  margin: 0 0 14px;
}

.reading-body :deep(p:empty),
.reading-body :deep(section:empty) {
  display: none;
}

.reading-body :deep(section),
.reading-body :deep(span) {
  max-width: 100%;
}

.reading-error {
  padding-top: 24px;
}
</style>

<template>
  <div class="space-y-4">
    <!-- 凭证 + RSS 入口 -->
    <el-row :gutter="16">
      <el-col :xs="24" :md="14">
        <el-card shadow="never" class="h-full">
          <template #header>
            <div class="flex items-center justify-between">
              <span class="font-bold">微信读书凭证</span>
              <el-tag :type="credentialTag.type" round>{{ credentialTag.text }}</el-tag>
            </div>
          </template>

          <template v-if="credential?.configured">
            <el-descriptions :column="1" size="small" border>
              <el-descriptions-item label="Cookie">
                <span class="text-xs text-gray-500">{{ credential.masked_cookie }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="最近校验">
                {{ fmtTime(credential.last_validated_at) }}
              </el-descriptions-item>
              <el-descriptions-item v-if="credential.last_error" label="说明">
                <span class="text-xs">{{ credential.last_error }}</span>
              </el-descriptions-item>
            </el-descriptions>
            <div class="mt-3 flex flex-wrap gap-2">
              <el-button size="small" type="primary" @click="startQrLogin">
                <el-icon class="mr-1"><Iphone /></el-icon>
                扫码登录
              </el-button>
              <el-button size="small" :loading="validating" @click="validateCredential">
                重新校验
              </el-button>
              <el-button size="small" :loading="refreshing" @click="refreshCookieNow">
                静默续期
              </el-button>
              <el-button size="small" plain @click="cookieDialogVisible = true">
                更新 Cookie
              </el-button>
            </div>
          </template>

          <template v-else>
            <el-empty :image-size="80" description="尚未配置微信读书 Cookie">
              <div class="flex gap-2">
                <el-button type="primary" @click="startQrLogin">
                  <el-icon class="mr-1"><Iphone /></el-icon>
                  扫码登录
                </el-button>
                <el-button @click="cookieDialogVisible = true">手动粘贴 Cookie</el-button>
              </div>
            </el-empty>
          </template>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="10">
        <el-card shadow="never" class="h-full">
          <template #header><span class="font-bold">RSS 订阅 & 自动同步</span></template>
          <div class="space-y-3 text-sm">
            <div class="flex items-center justify-between gap-2">
              <span class="text-gray-500">合并源</span>
              <div class="flex items-center gap-2 min-w-0">
                <span class="truncate text-blue-500 max-w-[180px]">{{ rssUrl() }}</span>
                <el-button size="small" text type="primary" @click="copyRss()">复制</el-button>
              </div>
            </div>
            <div class="flex items-center justify-between">
              <span class="text-gray-500">定时同步</span>
              <span>
                <el-tag v-if="scheduler?.enabled" type="success" size="small">
                  每 {{ scheduler.interval_minutes }} 分钟
                </el-tag>
                <el-tag v-else type="info" size="small">已关闭</el-tag>
              </span>
            </div>
            <div class="flex items-center justify-between">
              <span class="text-gray-500">Cookie 自动续期</span>
              <span class="flex items-center gap-1">
                <el-tag v-if="cookieRefresh?.enabled" type="success" size="small">
                  每 {{ cookieRefresh.interval_hours }} 小时
                </el-tag>
                <el-tag v-else type="info" size="small">已关闭</el-tag>
                <el-tooltip
                  v-if="cookieRefresh?.last_run_at"
                  :content="`上次续期 ${fmtTime(cookieRefresh.last_run_at)}${cookieRefresh.last_result?.message ? '：' + cookieRefresh.last_result.message : ''}`"
                >
                  <el-icon class="text-gray-400"><InfoFilled /></el-icon>
                </el-tooltip>
              </span>
            </div>
            <div class="flex items-center justify-between">
              <span class="text-gray-500">上次同步</span>
              <span>{{ fmtTime(scheduler?.last_run_at) }}</span>
            </div>
            <el-button
              type="primary"
              class="w-full"
              :loading="syncing"
              :disabled="!subscriptions.length"
              @click="syncAll"
            >
              立即同步全部（{{ subscriptions.length }} 个订阅）
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 订阅列表 -->
    <el-card shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <span class="font-bold">我的订阅（{{ subscriptions.length }}）</span>
          <div class="flex w-full max-w-md gap-2 sm:w-auto">
            <el-input
              v-model="newSubscriptionInput"
              placeholder="粘贴公众号文章链接 / 名称 / MP_WXS_xxx 均可订阅"
              clearable
              @keyup.enter="addSubscription"
            />
            <el-button type="primary" :loading="adding" @click="addSubscription">订阅</el-button>
          </div>
        </div>
      </template>

      <div v-if="subscriptionsError && !subscriptions.length" class="space-y-3">
        <el-alert type="error" :title="subscriptionsError" :closable="false" />
        <el-button size="small" @click="loadSubscriptions">重试</el-button>
      </div>

      <el-table v-else-if="subscriptions.length" :data="subscriptions" style="width: 100%">
        <el-table-column label="公众号" min-width="200">
          <template #default="{ row }">
            <div class="flex items-center gap-2">
              <el-avatar :size="32" :src="row.avatar" shape="square">{{ (row.name || "?")[0] }}</el-avatar>
              <div>
                <div class="font-medium">{{ row.name || row.book_id }}</div>
                <div class="text-xs text-gray-400">{{ row.book_id }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="文章数" width="90" align="center">
          <template #default="{ row }">{{ row.article_count }}</template>
        </el-table-column>
        <el-table-column label="最近同步" width="160">
          <template #default="{ row }">{{ fmtTime(row.last_sync_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.last_sync_status).type" size="small" round>
              {{ statusTag(row.last_sync_status).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openArticles(row)">文章</el-button>
            <el-button size="small" text type="primary" @click="syncOne(row)">同步</el-button>
            <el-button size="small" text @click="copyRss(row.book_id)">RSS</el-button>
            <el-button size="small" text type="danger" @click="removeSubscription(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-else-if="!subscriptionsError" description="还没有订阅任何公众号。微信读书 App 订阅后，复制公众号主页链接粘贴到上方即可。" />
    </el-card>

    <!-- 文章抽屉（列表 / 阅读双视图） -->
    <el-drawer
      v-model="articlesVisible"
      :title="readingArticle ? '' : `文章 · ${currentSub?.name || ''}`"
      size="640px"
      :with-header="!readingArticle"
    >
      <!-- 阅读视图 -->
      <div v-if="readingArticle" class="reading-view">
        <div class="reading-top">
          <el-button size="small" @click="backToList">
            <el-icon class="mr-1"><ArrowLeft /></el-icon>
            返回列表
          </el-button>
          <a :href="readingArticle.link" target="_blank" rel="noopener" class="reading-origin">
            微信原文
          </a>
        </div>
        <h2 class="reading-title">{{ readingArticle.title || "(无标题)" }}</h2>
        <div class="reading-meta">{{ fmtTime(readingArticle.publish_time || null) }}</div>

        <div v-loading="readingLoading" class="reading-body-wrap">
          <div v-if="readingError" class="reading-error">
            <el-alert type="error" :title="readingError" :closable="false" />
            <el-button class="mt-3" size="small" @click="openArticle(readingArticle)">重试</el-button>
          </div>
          <!-- 正文来自微信读书接口，图片已加 no-referrer；v-html 渲染富文本 -->
          <div v-else-if="readingContent" class="reading-body" v-html="readingContent.content_html"></div>
        </div>
      </div>

      <!-- 列表视图 -->
      <div v-else v-loading="articlesLoading" class="space-y-3">
        <div
          v-for="article in articles"
          :key="article.review_id"
          class="article-card"
          @click="openArticle(article)"
        >
          <div class="text-sm font-medium leading-6">{{ article.title || "(无标题)" }}</div>
          <div class="mt-1 text-xs text-gray-400">{{ fmtTime(article.publish_time || null) }}</div>
        </div>
        <el-button
          v-if="articlesCursor"
          class="w-full"
          :loading="articlesLoading"
          @click="loadMoreArticles"
        >
          加载更多
        </el-button>
        <div v-if="articlesError && !articles.length" class="space-y-3 py-4">
          <el-alert type="error" :title="articlesError" :closable="false" />
          <el-button class="w-full" size="small" @click="loadMoreArticles">重试</el-button>
        </div>
        <div v-else-if="!articles.length && !articlesLoading" class="text-center text-sm text-gray-400">
          暂无文章，可点击「同步」拉取最新一篇
        </div>
      </div>
    </el-drawer>

    <!-- 订阅向导：已识别公众号，引导补充微信读书链接 -->
    <el-dialog v-model="wizardVisible" title="完成订阅" width="480px">
      <div class="space-y-4">
        <el-alert type="success" :closable="false">
          已识别公众号：<b>「{{ wizardName }}」</b>，还差最后一步——补充它在微信读书里的链接。
        </el-alert>
        <div class="text-sm leading-7 text-gray-600">
          公众号只能在<b>手机微信读书 App</b> 里搜索（网页版不收录）：<br />
          1. 打开微信读书 App，搜索 <b>{{ wizardName }}</b><br />
          2. 进入该公众号主页 → 右上角「⋯」→ 复制链接<br />
          3. 粘贴到下方完成订阅
        </div>
        <el-input v-model="wizardInput" placeholder="https://weread.qq.com/...MP_WXS_xxx... 或 MP_WXS_xxx" clearable @keyup.enter="submitWizard" />
        <el-button class="w-full" type="primary" :loading="adding" @click="submitWizard">完成订阅</el-button>
      </div>
    </el-dialog>

    <!-- 扫码登录状态对话框 -->
    <el-dialog
      v-model="qrDialogVisible"
      title="微信读书 · 扫码登录"
      width="460px"
      :close-on-click-modal="false"
      @close="closeQrDialog"
    >
      <div class="space-y-4">
        <div class="flex items-center gap-2">
          <el-tag :type="qrStateTag.type" size="large" round>{{ qrStateTag.text }}</el-tag>
          <span
            v-if="['pending', 'validating'].includes(qrStatus?.state || '')"
            class="text-sm text-gray-400"
          >
            <el-icon class="mr-1 align-middle is-loading"><Loading /></el-icon>
          </span>
        </div>
        <div class="text-sm leading-6">{{ qrStatus?.message || "正在启动…" }}</div>
        <el-alert type="info" :closable="false">
          已在服务器所在电脑弹出浏览器窗口，二维码在窗口里。用手机微信「扫一扫」确认登录即可，
          全程无需手动复制 Cookie。
        </el-alert>
        <div v-if="qrStatus?.state === 'failed'" class="flex gap-2">
          <el-button size="small" type="primary" @click="startQrLogin">重试</el-button>
          <el-button size="small" @click="cancelQrLogin">取消会话</el-button>
        </div>
        <el-button v-else-if="['pending', 'validating'].includes(qrStatus?.state || '')" size="small" @click="cancelQrLogin">
          取消扫码
        </el-button>
      </div>
    </el-dialog>

    <!-- Cookie 设置对话框 -->
    <el-dialog v-model="cookieDialogVisible" title="微信读书 Cookie" width="560px">
      <el-alert type="info" :closable="false" class="mb-3">
        浏览器登录 weread.qq.com → F12 → Network → 任选一个请求 → Request Headers 复制完整 Cookie。
      </el-alert>
      <el-input
        v-model="cookieInput"
        type="textarea"
        :rows="5"
        placeholder="wr_vid=...; wr_skey=...;（完整一串）"
      />
      <template #footer>
        <el-button @click="cookieDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingCookie" @click="saveCookie">保存并校验</el-button>
      </template>
    </el-dialog>
  </div>
</template>
