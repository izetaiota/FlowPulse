<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { accountApi, type AccountItem, type PlatformInfo } from "@/api/accounts";

const platforms = ref<PlatformInfo[]>([]);
const accounts = ref<AccountItem[]>([]);
const loading = ref(false);
const activePlatform = ref("");
const checkingIds = ref<number[]>([]);

// 平台筛选（全部 + 各平台）
const filters = computed(() => [
  { id: "", label: "全部" },
  ...platforms.value.map((p) => ({ id: p.id, label: p.label })),
]);
const managedPlatforms = computed(() => platforms.value.filter((p) => p.managed));

async function load() {
  loading.value = true;
  try {
    const [platformResult, accountResult] = await Promise.all([
      accountApi.platforms(),
      accountApi.list(activePlatform.value || undefined),
    ]);
    platforms.value = platformResult.platforms;
    accounts.value = accountResult.accounts;
  } catch {
    ElMessage.error("账号列表加载失败");
  } finally {
    loading.value = false;
  }
}

function platformLabel(id: string): string {
  return platforms.value.find((p) => p.id === id)?.label ?? id;
}

function statusTag(status: string):
  { label: string; type: "success" | "danger" | "info" | "warning" } {
  switch (status) {
    case "active":
      return { label: "正常", type: "success" };
    case "expired":
      return { label: "已失效", type: "danger" };
    case "disabled":
      return { label: "已停用", type: "warning" };
    default:
      return { label: "未验证", type: "info" };
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
}

async function checkAccount(account: AccountItem) {
  checkingIds.value.push(account.id);
  try {
    const result = await accountApi.check(account.id);
    if (result.ok === true) {
      ElMessage.success(`体检通过：${result.message || "登录态正常"}`);
    } else if (result.ok === false) {
      ElMessage.warning(`体检未通过：${result.message || "登录态失效"}`);
    } else {
      ElMessage.info(result.message);
    }
    await load();
  } catch {
    ElMessage.error("体检请求失败");
  } finally {
    checkingIds.value = checkingIds.value.filter((id) => id !== account.id);
  }
}

async function removeAccount(account: AccountItem) {
  const tip =
    account.kind === "builtin" ? "将同时清除所属模块保存的登录凭证。" : "仅移除本条登记记录。";
  try {
    await ElMessageBox.confirm(`确定删除「${account.name}」？${tip}`, "删除账号", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await accountApi.remove(account.id);
    ElMessage.success("已删除");
    await load();
  } catch {
    ElMessage.error("删除失败");
  }
}

// ---- 手动登记账号（P3+ 浏览器登录落地前的占位登记） ----
const createVisible = ref(false);
const creating = ref(false);
const form = ref({ platform: "douyin", account_key: "", name: "", credential: "" });

function openCreate() {
  form.value = {
    platform: managedPlatforms.value[0]?.id ?? "douyin",
    account_key: "",
    name: "",
    credential: "",
  };
  createVisible.value = true;
}

async function submitCreate() {
  if (!form.value.account_key.trim()) {
    ElMessage.warning("请填写账号标识（如 sec_uid / 用户 ID）");
    return;
  }
  creating.value = true;
  try {
    await accountApi.create({
      platform: form.value.platform,
      account_key: form.value.account_key.trim(),
      name: form.value.name.trim() || form.value.account_key.trim(),
      credential: form.value.credential.trim(),
    });
    ElMessage.success("已登记");
    createVisible.value = false;
    await load();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data
      ?.detail;
    ElMessage.error(detail || "登记失败");
  } finally {
    creating.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <!-- 说明与操作 -->
    <el-card shadow="never">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="fp-card-title">统一账号中心</h2>
          <p class="fp-card-desc">
            公众号、小红书等内置模块账号自动汇入本列表；抖音 / 快手 / 视频号 / TikTok
            可先手动登记，浏览器登录层落地后升级为在线账号。
          </p>
        </div>
        <div class="flex gap-2">
          <el-button @click="load" :loading="loading">刷新</el-button>
          <el-button type="primary" @click="openCreate">登记账号</el-button>
        </div>
      </div>
    </el-card>

    <!-- 平台筛选 -->
    <el-card shadow="never">
      <el-radio-group v-model="activePlatform" @change="load">
        <el-radio-button v-for="f in filters" :key="f.id" :value="f.id">
          {{ f.label }}
        </el-radio-button>
      </el-radio-group>

      <el-table :data="accounts" v-loading="loading" class="mt-3">
        <el-table-column label="平台" width="150">
          <template #default="{ row }">
            <el-tag effect="plain">{{ platformLabel(row.platform) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="account_key" label="账号标识" min-width="110" />
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag :type="row.kind === 'builtin' ? 'primary' : 'info'" size="small">
              {{ row.kind === "builtin" ? "模块账号" : "手动登记" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status).type">{{ statusTag(row.status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近体检" min-width="160">
          <template #default="{ row }">
            <span>{{ formatTime(row.last_check_at) }}</span>
            <el-tooltip
              v-if="row.last_check_message"
              :content="row.last_check_message"
              placement="top"
            >
              <el-icon class="ml-1 align-middle text-slate-400"><WarningFilled /></el-icon>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              :loading="checkingIds.includes(row.id)"
              @click="checkAccount(row)"
            >
              体检
            </el-button>
            <el-button size="small" type="danger" plain @click="removeAccount(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无账号：公众号 / 小红书在工作台登录后自动出现在这里" />
        </template>
      </el-table>
    </el-card>

    <!-- 登记账号弹窗 -->
    <el-dialog v-model="createVisible" title="登记账号" width="480px">
      <el-form label-width="90px">
        <el-form-item label="平台">
          <el-select v-model="form.platform">
            <el-option
              v-for="p in managedPlatforms"
              :key="p.id"
              :label="p.label"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="账号标识">
          <el-input
            v-model="form.account_key"
            placeholder="如 sec_uid / 用户 ID，同平台内唯一"
          />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="备注名（可选）" />
        </el-form-item>
        <el-form-item label="凭证">
          <el-input
            v-model="form.credential"
            type="textarea"
            :rows="3"
            placeholder="Cookie 等凭证（可选，加密存储）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">登记</el-button>
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
