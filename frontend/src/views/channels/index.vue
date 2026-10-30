<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { channelsApi, type ChannelsProfile, type ChannelsStatus, type ChannelsWork } from "@/api/channels";

const status = ref<ChannelsStatus | null>(null);
const profile = ref<ChannelsProfile | null>(null);
const works = ref<ChannelsWork[]>([]);
const loading = ref(false);
const refreshing = ref(false);
const qrMessage = ref("");
const qrPolling = ref<number | null>(null);

async function load() {
  loading.value = true;
  try {
    const [statusResult, profileResult, worksResult] = await Promise.all([
      channelsApi.status(),
      channelsApi.profile(),
      channelsApi.works(),
    ]);
    status.value = statusResult;
    profile.value = profileResult.profile;
    works.value = worksResult.works;
  } catch {
    ElMessage.error("视频号数据加载失败");
  } finally {
    loading.value = false;
  }
}

async function refresh() {
  refreshing.value = true;
  try {
    const result = await channelsApi.refresh();
    if (result.ok) {
      ElMessage.success(`已刷新：${result.nickname ?? ""}，${result.works_count ?? 0} 条作品`);
      await load();
    } else {
      ElMessage.warning(result.error || "刷新失败");
    }
  } catch {
    ElMessage.error("刷新请求失败");
  } finally {
    refreshing.value = false;
  }
}

async function startQrLogin() {
  try {
    const started = await channelsApi.qrStart();
    qrMessage.value = started.message;
    ElMessage.info("已在本机打开浏览器，请扫码登录视频号助手");
    if (qrPolling.value) window.clearInterval(qrPolling.value);
    qrPolling.value = window.setInterval(async () => {
      const state = await channelsApi.qrPoll(started.session_id);
      qrMessage.value = state.message;
      if (state.state === "logged_in") {
        stopQrPolling();
        ElMessage.success("登录成功，账号已保存");
        await load();
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

async function clearAccount() {
  try {
    await ElMessageBox.confirm("删除视频号账号（登录态与本地快照保留）？", "删除账号", {
      type: "warning",
    });
  } catch {
    return;
  }
  await channelsApi.clear();
  ElMessage.success("已删除");
  await load();
}

function formatTime(ts: number): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 16);
}

onMounted(load);
onUnmounted(stopQrPolling);
</script>

<template>
  <div class="space-y-4" v-loading="loading">
    <!-- 账号与资料 -->
    <el-card shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span class="font-bold">视频号（本账号）</span>
            <span class="ml-3 text-xs text-slate-400">
              {{ status?.configured
                ? `已登录${status.nickname ? " · " + status.nickname : ""} · ${status.works_count} 条作品快照`
                : "未登录（视频号仅支持本账号数据）" }}
            </span>
          </div>
          <div class="flex gap-2">
            <el-button size="small" @click="load">刷新列表</el-button>
            <el-button size="small" type="primary" :loading="refreshing" :disabled="!status?.configured" @click="refresh">
              拉取最新数据
            </el-button>
            <el-button v-if="!status?.configured" size="small" type="primary" @click="startQrLogin">
              浏览器扫码
            </el-button>
            <el-button v-if="status?.configured" size="small" type="danger" plain @click="clearAccount">
              删除账号
            </el-button>
          </div>
        </div>
      </template>
      <p v-if="qrMessage" class="m-0 text-xs text-slate-500">{{ qrMessage }}</p>
      <el-alert
        v-if="status?.configured"
        type="info"
        :closable="false"
        class="mt-1"
        title="视频号媒体走加密 CDN，无法直接下载——这里只记录作品元数据与互动数据（点赞/评论/转发）。"
      />
    </el-card>

    <!-- 作品列表 -->
    <el-card shadow="never">
      <template #header>
        <span class="font-bold">作品数据（{{ works.length }}）</span>
      </template>
      <el-table :data="works" size="small">
        <el-table-column label="标题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ row.title || row.object_id }}</template>
        </el-table-column>
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.media_type === 'video' ? 'danger' : 'info'">
              {{ row.media_type === "video" ? "视频" : "图文" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="liked_count" label="点赞" width="90" />
        <el-table-column prop="comment_count" label="评论" width="90" />
        <el-table-column prop="forward_count" label="转发" width="90" />
        <el-table-column label="发布时间" width="150">
          <template #default="{ row }">{{ formatTime(row.create_time) }}</template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无数据：登录后点「拉取最新数据」" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>
