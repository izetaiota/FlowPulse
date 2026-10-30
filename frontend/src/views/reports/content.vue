<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { reportApi, type ReportKind } from "@/api/reports";

const reports = ref<ReportKind[]>([]);
const loading = ref(false);

const icons: Record<string, string> = {
  "xhs-monitors": "PictureFilled",
  "xhs-contents": "Picture",
  "douyin-monitors": "VideoCamera",
  "douyin-contents": "VideoPlay",
  downloads: "Download",
  accounts: "Connection",
};

async function load() {
  loading.value = true;
  try {
    const result = await reportApi.list();
    reports.value = result.reports;
  } catch {
    ElMessage.error("报表清单加载失败");
  } finally {
    loading.value = false;
  }
}

function download(kind: ReportKind) {
  window.open(reportApi.downloadUrl(kind.kind), "_blank");
  ElMessage.success(`正在导出「${kind.label}」`);
}

onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <el-card shadow="never" v-loading="loading">
      <template #header>
        <div class="flex items-center justify-between">
          <div>
            <span class="font-bold">报表导出</span>
            <span class="ml-3 text-xs text-slate-400">
              站内数据一键导出 Excel（监控目标 / 作品记录 / 下载历史 / 账号清单）
            </span>
          </div>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </template>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="report in reports"
          :key="report.kind"
          class="fp-report-card"
          @click="download(report)"
        >
          <div class="flex items-center gap-3">
            <el-icon :size="22" class="text-indigo-500">
              <component :is="icons[report.kind] || 'Document'" />
            </el-icon>
            <div class="min-w-0">
              <div class="fp-report-title">{{ report.label }}</div>
              <div class="fp-report-desc">{{ report.desc }}</div>
            </div>
          </div>
          <el-button size="small" type="primary" plain class="mt-3 w-full">导出 Excel</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.fp-report-card {
  padding: 16px;
  border: 1px solid #e8eaf0;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.fp-report-card:hover {
  border-color: #c7d2fe;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06);
}

.fp-report-title {
  font-size: 14px;
  font-weight: 600;
}

.fp-report-desc {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 2px;
}
</style>
