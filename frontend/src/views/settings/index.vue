<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { menuApi, type MenuItemData } from "@/api/menu";
import { authApi } from "@/api/auth";
import { useAuthStore } from "@/stores/auth";
import { useMenuStore } from "@/stores/menu";

const menuStore = useMenuStore();
const authStore = useAuthStore();
const rows = ref<MenuItemData[]>([]);
const loading = ref(false);
const saving = ref(false);
const loadError = ref("");

async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    const { menus } = await menuApi.list();
    rows.value = menus.map((m) => ({ ...m }));
    refreshParentOptions();
  } catch {
    loadError.value = "菜单加载失败，请确认后端服务正常后重试。";
  } finally {
    loading.value = false;
  }
}

const parentOptions = ref<{ id: string; title: string }[]>([]);
function refreshParentOptions() {
  parentOptions.value = rows.value
    .filter((r) => !r.parent)
    .map((r) => ({ id: r.id, title: r.title }));
}

function move(index: number, delta: number) {
  const target = index + delta;
  if (target < 0 || target >= rows.value.length) return;
  const list = [...rows.value];
  [list[index], list[target]] = [list[target], list[index]];
  rows.value = list;
}

function addChild(parent: string) {
  rows.value.push({
    id: "",
    title: "新子菜单",
    path: "/",
    icon: "",
    parent,
    visible: true,
  });
}

function addTop() {
  rows.value.push({
    id: "",
    title: "新菜单",
    path: "/",
    icon: "Menu",
    parent: "",
    visible: true,
  });
}

async function removeRow(index: number) {
  const row = rows.value[index];
  const hasChildren = rows.value.some((r) => r.parent && r.parent === row.id);
  if (hasChildren) {
    ElMessage.warning("该菜单下还有子菜单，请先删除子菜单");
    return;
  }
  await ElMessageBox.confirm(`删除菜单「${row.title}」？`, "删除", { type: "warning" });
  rows.value.splice(index, 1);
  refreshParentOptions();
}

async function save() {
  const ids = new Set<string>();
  for (const row of rows.value) {
    if (!row.title.trim() || !row.path.trim()) {
      ElMessage.warning("标题和路径不能为空");
      return;
    }
    if (row.id && ids.has(row.id)) {
      ElMessage.warning(`菜单标识重复：${row.id}`);
      return;
    }
    if (row.id) ids.add(row.id);
  }
  saving.value = true;
  try {
    await menuApi.save(rows.value);
    ElMessage.success("菜单已保存");
    await load();
    await menuStore.load(true);
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(typeof detail === "string" ? detail : "保存失败");
  } finally {
    saving.value = false;
  }
}

async function resetDefaults() {
  await ElMessageBox.confirm("恢复为默认菜单？当前自定义配置将被覆盖。", "恢复默认", { type: "warning" });
  try {
    await menuApi.reset();
    ElMessage.success("已恢复默认菜单");
    await load();
    await menuStore.load(true);
  } catch {
    ElMessage.error("恢复失败");
  }
}

onMounted(load);

// --- 登录账号（改密；账号名不可改，密码存库为哈希） ---
const passwordForm = reactive({ oldPassword: "", newPassword: "", confirm: "" });
const changingPassword = ref(false);

async function changePassword() {
  if (!passwordForm.oldPassword || !passwordForm.newPassword) {
    ElMessage.warning("请填写旧密码和新密码");
    return;
  }
  if (passwordForm.newPassword.length < 6) {
    ElMessage.warning("新密码至少 6 位");
    return;
  }
  if (passwordForm.newPassword !== passwordForm.confirm) {
    ElMessage.warning("两次输入的新密码不一致");
    return;
  }
  changingPassword.value = true;
  try {
    await authApi.changePassword(passwordForm.oldPassword, passwordForm.newPassword);
    ElMessage.success("密码已更新，下次登录请使用新密码");
    passwordForm.oldPassword = "";
    passwordForm.newPassword = "";
    passwordForm.confirm = "";
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(typeof detail === "string" ? detail : "修改失败");
  } finally {
    changingPassword.value = false;
  }
}
</script>

<template>
  <div class="space-y-4">
    <el-card shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="font-bold">侧栏菜单管理</span>
          <div class="flex gap-2">
            <el-button size="small" @click="resetDefaults">恢复默认</el-button>
            <el-button size="small" @click="addTop">新增菜单</el-button>
            <el-button size="small" type="primary" :loading="saving" @click="save">保存</el-button>
          </div>
        </div>
      </template>

      <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" class="mb-3">
        <el-button size="small" class="mt-2" @click="load">重试</el-button>
      </el-alert>

      <el-table v-if="rows.length" :data="rows" v-loading="loading">
        <el-table-column label="标题" min-width="140">
          <template #default="{ row }">
            <el-input v-model="row.title" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="路径" min-width="170">
          <template #default="{ row }">
            <el-input v-model="row.path" size="small" placeholder="/xxx" />
          </template>
        </el-table-column>
        <el-table-column label="图标" width="140">
          <template #default="{ row }">
            <el-input v-model="row.icon" size="small" placeholder="Element 图标名" />
          </template>
        </el-table-column>
        <el-table-column label="父级" width="150">
          <template #default="{ row }">
            <el-select
              v-if="!row.parent"
              :model-value="''"
              size="small"
              placeholder="无（顶级）"
              disabled
            />
            <el-select v-else v-model="row.parent" size="small">
              <el-option
                v-for="opt in parentOptions.filter((o) => o.id !== row.id)"
                :key="opt.id"
                :label="opt.title"
                :value="opt.id"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="可见" width="70" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.visible" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" align="center">
          <template #default="{ row, $index }">
            <el-button size="small" text @click="move($index, -1)">上移</el-button>
            <el-button size="small" text @click="move($index, 1)">下移</el-button>
            <el-button v-if="!row.parent" size="small" text type="primary" @click="addChild(row.id || row.path)">加子项</el-button>
            <el-button size="small" text type="danger" @click="removeRow($index)">删</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mt-3 text-xs text-gray-400">
        菜单存于数据库（DATABASE_URL 模式）或 data/app/menus.json；标识留空自动生成；
        图标使用 Element Plus 图标名（如 Odometer、Reading）；保存后侧栏即时生效。
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header><span class="font-bold">登录账号</span></template>
      <template v-if="authStore.enabled">
        <div class="mb-3 text-sm">
          当前账号：<span class="font-medium">{{ authStore.username || "admin" }}</span>
          <span class="ml-2 text-xs text-gray-400">账号密码存储于数据库（fp_users，密码仅存哈希）</span>
        </div>
        <el-form label-width="90px" class="max-w-md" @submit.prevent>
          <el-form-item label="旧密码">
            <el-input v-model="passwordForm.oldPassword" type="password" show-password autocomplete="current-password" />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="passwordForm.newPassword" type="password" show-password autocomplete="new-password" placeholder="至少 6 位" />
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input v-model="passwordForm.confirm" type="password" show-password autocomplete="new-password" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="changingPassword" @click="changePassword">修改密码</el-button>
          </el-form-item>
        </el-form>
      </template>
      <el-alert
        v-else
        type="info"
        :closable="false"
        title="鉴权未启用：未配置 ADMIN_PASSWORD，Web 端无需登录。配置环境变量并重启后，账号会自动写入数据库。"
      />
    </el-card>

    <el-card shadow="never">
      <template #header><span class="font-bold">更多设置（规划中）</span></template>
      <el-empty
        :image-size="70"
        description="私有化部署配置中心：安全设置、存储与定时同步周期、Webhook 通知、日志管理。"
      />
    </el-card>
  </div>
</template>
