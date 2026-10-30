<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { queueApi, type QueueItem } from "@/api/queue";
import { dmApi, type DmConversation, type DmDraft, type DmMessage, type DmRule } from "@/api/dm";

const activeTab = ref("tasks");
watch(activeTab, (tab) => {
  if (tab === "dm" && !conversations.value.length && !dmLoading.value) {
    loadConversations();
  }
});

// ---- 私信（小红书） ----
const conversations = ref<DmConversation[]>([]);
const dmLoading = ref(false);
const dmMessage = ref("");
const rules = ref<DmRule[]>([]);
const drafts = ref<DmDraft[]>([]);
const messagesVisible = ref(false);
const messagesLoading = ref(false);
const messages = ref<DmMessage[]>([]);
const messagesPeer = ref("");
const ruleDialogVisible = ref(false);
const ruleForm = ref({ name: "", keywords: "", reply_template: "" });
const ruleSaving = ref(false);

async function loadConversations() {
  dmLoading.value = true;
  try {
    const result = await dmApi.conversations();
    conversations.value = result.conversations;
    dmMessage.value = result.message;
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    dmMessage.value = detail || "会话同步失败";
    conversations.value = [];
  } finally {
    dmLoading.value = false;
  }
  // 规则与草稿独立加载：会话同步失败（如未登录）不影响规则管理
  await Promise.all([loadRules(), loadDrafts()]);
}

async function openMessages(conv: DmConversation) {
  messagesPeer.value = conv.peer_nickname || conv.peer_uid;
  messagesVisible.value = true;
  messagesLoading.value = true;
  try {
    const result = await dmApi.messages(conv.conv_id, conv.peer_uid);
    messages.value = result.messages;
  } catch {
    messages.value = [];
    ElMessage.error("消息加载失败");
  } finally {
    messagesLoading.value = false;
  }
}

async function loadRules() {
  const result = await dmApi.listRules();
  rules.value = result.rules;
}

async function loadDrafts() {
  const result = await dmApi.listDrafts();
  drafts.value = result.drafts;
}

async function saveRule() {
  if (!ruleForm.value.name.trim() || !ruleForm.value.keywords.trim() || !ruleForm.value.reply_template.trim()) {
    ElMessage.warning("请完整填写规则名、关键词与回复模板");
    return;
  }
  ruleSaving.value = true;
  try {
    await dmApi.createRule(ruleForm.value);
    ElMessage.success("规则已创建，下次同步会话时生效");
    ruleDialogVisible.value = false;
    ruleForm.value = { name: "", keywords: "", reply_template: "" };
    await loadRules();
  } catch {
    ElMessage.error("创建失败");
  } finally {
    ruleSaving.value = false;
  }
}

async function toggleRule(rule: DmRule) {
  await dmApi.updateRule(rule.id, { enabled: !rule.enabled });
  await loadRules();
}

async function removeRule(rule: DmRule) {
  await dmApi.removeRule(rule.id);
  await loadRules();
}

async function reviewDraft(draft: DmDraft, decision: "approved" | "rejected") {
  await dmApi.reviewDraft(draft.id, decision);
  ElMessage.success(decision === "approved" ? "已通过（请到小红书手动发送）" : "已拒绝");
  await loadDrafts();
}

function dmTime(ts: number): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toISOString().replace("T", " ").slice(5, 16);
}

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
    <el-tabs v-model="activeTab">
      <el-tab-pane label="任务动态" name="tasks" />
      <el-tab-pane label="私信（小红书）" name="dm" />
    </el-tabs>
    <el-card v-if="activeTab === 'tasks'" shadow="never">
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

    <el-card v-if="activeTab === 'tasks'" shadow="never">
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
  
    <!-- 私信（小红书） -->
    <template v-if="activeTab === 'dm'">
      <el-card shadow="never" v-loading="dmLoading">
        <template #header>
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <span class="font-bold">会话列表（小红书）</span>
              <span v-if="dmMessage" class="ml-3 text-xs text-slate-400">{{ dmMessage }}</span>
            </div>
            <el-button size="small" @click="loadConversations" :loading="dmLoading">同步会话</el-button>
          </div>
        </template>
        <el-table :data="conversations" size="small">
          <el-table-column prop="peer_nickname" label="对方" min-width="120" />
          <el-table-column prop="last_text" label="最近消息" min-width="220" show-overflow-tooltip />
          <el-table-column label="未读" width="70">
            <template #default="{ row }">
              <el-badge v-if="row.unread_count > 0" :value="row.unread_count" type="danger" />
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="130">
            <template #default="{ row }">{{ dmTime(row.last_time) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openMessages(row)">查看</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="点击「同步会话」拉取小红书私信（需已登录小红书）" />
          </template>
        </el-table>
      </el-card>

      <el-row :gutter="16">
        <el-col :xs="24" :md="12">
          <el-card shadow="never">
            <template #header>
              <div class="flex items-center justify-between">
                <span class="font-bold">自动回复规则</span>
                <el-button size="small" type="primary" @click="ruleDialogVisible = true">新增规则</el-button>
              </div>
            </template>
            <el-table :data="rules" size="small">
              <el-table-column prop="name" label="名称" min-width="100" />
              <el-table-column prop="keywords" label="关键词" min-width="120" show-overflow-tooltip />
              <el-table-column label="启用" width="70">
                <template #default="{ row }">
                  <el-switch size="small" :model-value="row.enabled" @change="toggleRule(row)" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="70" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="danger" plain @click="removeRule(row)">删</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <el-empty description="暂无规则：按关键词匹配未读消息生成建议回复" />
              </template>
            </el-table>
          </el-card>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-card shadow="never">
            <template #header>
              <span class="font-bold">建议回复（人工审核）</span>
            </template>
            <el-table :data="drafts.filter((d) => d.status === 'pending')" size="small">
              <el-table-column prop="peer_nickname" label="来自" min-width="90" />
              <el-table-column prop="last_text" label="消息" min-width="130" show-overflow-tooltip />
              <el-table-column prop="suggested_reply" label="建议回复" min-width="150" show-overflow-tooltip />
              <el-table-column label="操作" width="140" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" plain @click="reviewDraft(row, 'approved')">通过</el-button>
                  <el-button size="small" plain @click="reviewDraft(row, 'rejected')">拒绝</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <el-empty description="暂无待审核回复：同步会话时按规则自动生成" />
              </template>
            </el-table>
          </el-card>
        </el-col>
      </el-row>
    </template>

    <!-- 消息抽屉 -->
    <el-drawer v-model="messagesVisible" :title="`与 ${messagesPeer} 的对话`" size="420px">
      <div v-loading="messagesLoading" class="space-y-2">
        <div
          v-for="msg in messages"
          :key="msg.server_msg_id"
          class="flex"
          :class="msg.direction === 'in' ? 'justify-start' : 'justify-end'"
        >
          <div
            class="fp-bubble"
            :class="msg.direction === 'in' ? 'fp-bubble-in' : 'fp-bubble-out'"
          >
            {{ msg.text || `[${msg.msg_type}]` }}
          </div>
        </div>
        <el-empty v-if="!messagesLoading && !messages.length" description="无消息" />
      </div>
    </el-drawer>

    <!-- 规则弹窗 -->
    <el-dialog v-model="ruleDialogVisible" title="新增回复规则" width="480px">
      <el-form label-width="90px">
        <el-form-item label="规则名">
          <el-input v-model="ruleForm.name" placeholder="如：价格咨询" />
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="ruleForm.keywords" placeholder="逗号分隔，命中任一即匹配" />
        </el-form-item>
        <el-form-item label="回复模板">
          <el-input v-model="ruleForm.reply_template" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="ruleSaving" @click="saveRule">创建</el-button>
      </template>
    </el-dialog>
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

<style scoped>
.fp-bubble {
  max-width: 78%;
  padding: 6px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

.fp-bubble-in {
  background: #f1f3f7;
  color: #1f2937;
}

.fp-bubble-out {
  background: var(--el-color-primary);
  color: #fff;
}
</style>
