<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { adminApi, type AdminRole, type AdminUser } from "@/api/admin";

const activeTab = ref("users");
const users = ref<AdminUser[]>([]);
const roles = ref<AdminRole[]>([]);
const permCodes = ref<string[]>([]);
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    const [userResult, roleResult, permResult] = await Promise.all([
      adminApi.listUsers().catch(() => ({ users: [] as AdminUser[] })),
      adminApi.listRoles().catch(() => ({ roles: [] as AdminRole[] })),
      adminApi.listPermCodes().catch(() => ({ codes: [] as string[] })),
    ]);
    users.value = userResult.users;
    roles.value = roleResult.roles;
    permCodes.value = permResult.codes;
  } finally {
    loading.value = false;
  }
}

// ---- 用户 ----
const userDialogVisible = ref(false);
const userSaving = ref(false);
const userForm = ref({ username: "", password: "", roles: [] as string[] });
const editingUser = ref<string>("");

function openCreateUser() {
  editingUser.value = "";
  userForm.value = { username: "", password: "", roles: [] };
  userDialogVisible.value = true;
}

function openEditUser(user: AdminUser) {
  editingUser.value = user.username;
  userForm.value = { username: user.username, password: "", roles: [...user.roles] };
  userDialogVisible.value = true;
}

async function saveUser() {
  if (!editingUser.value && !userForm.value.username.trim()) {
    ElMessage.warning("请填写用户名");
    return;
  }
  if (!editingUser.value && userForm.value.password.length < 6) {
    ElMessage.warning("密码至少 6 位");
    return;
  }
  userSaving.value = true;
  try {
    if (editingUser.value) {
      await adminApi.updateUser(editingUser.value, {
        password: userForm.value.password || undefined,
        roles: userForm.value.roles,
      });
    } else {
      await adminApi.createUser({
        username: userForm.value.username.trim(),
        password: userForm.value.password,
        roles: userForm.value.roles,
      });
    }
    ElMessage.success("已保存");
    userDialogVisible.value = false;
    await load();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "保存失败");
  } finally {
    userSaving.value = false;
  }
}

async function removeUser(user: AdminUser) {
  if (user.username === "admin") {
    ElMessage.warning("不能删除内置 admin 账号");
    return;
  }
  try {
    await ElMessageBox.confirm(`删除用户「${user.username}」？`, "删除", { type: "warning" });
  } catch {
    return;
  }
  try {
    await adminApi.deleteUser(user.username);
    ElMessage.success("已删除");
    await load();
  } catch {
    ElMessage.error("删除失败");
  }
}

// ---- 角色 ----
const roleDialogVisible = ref(false);
const roleSaving = ref(false);
const roleForm = ref({ code: "", name: "", remark: "", perms: [] as string[] });
const editingRole = ref<string>("");

function openCreateRole() {
  editingRole.value = "";
  roleForm.value = { code: "", name: "", remark: "", perms: [] };
  roleDialogVisible.value = true;
}

function openEditRole(role: AdminRole) {
  editingRole.value = role.code;
  roleForm.value = { code: role.code, name: role.name, remark: role.remark, perms: [...role.perms] };
  roleDialogVisible.value = true;
}

async function saveRole() {
  if (!editingRole.value && !/^[a-z][a-z0-9_]*$/.test(roleForm.value.code)) {
    ElMessage.warning("角色编码需小写字母开头，仅含 a-z/0-9/_");
    return;
  }
  roleSaving.value = true;
  try {
    if (editingRole.value) {
      await adminApi.updateRole(editingRole.value, {
        name: roleForm.value.name,
        remark: roleForm.value.remark,
        perms: roleForm.value.perms,
      });
    } else {
      await adminApi.createRole({
        code: roleForm.value.code,
        name: roleForm.value.name,
        remark: roleForm.value.remark,
        perms: roleForm.value.perms,
      });
    }
    ElMessage.success("已保存");
    roleDialogVisible.value = false;
    await load();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "保存失败");
  } finally {
    roleSaving.value = false;
  }
}

async function removeRole(role: AdminRole) {
  if (role.code === "admin") {
    ElMessage.warning("不能删除内置 admin 角色");
    return;
  }
  try {
    await ElMessageBox.confirm(
      `删除角色「${role.name || role.code}」？${role.users.length ? `仍有 ${role.users.length} 个用户挂载` : ""}`,
      "删除",
      { type: "warning" },
    );
  } catch {
    return;
  }
  try {
    await adminApi.deleteRole(role.code);
    ElMessage.success("已删除");
    await load();
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    ElMessage.error(detail || "删除失败");
  }
}

onMounted(load);
</script>

<template>
  <div class="space-y-4" v-loading="loading">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="用户管理" name="users" />
      <el-tab-pane label="角色管理" name="roles" />
    </el-tabs>

    <!-- 用户管理 -->
    <template v-if="activeTab === 'users'">
      <el-card shadow="never">
        <template #header>
          <div class="flex items-center justify-between">
            <span class="font-bold">用户列表</span>
            <el-button type="primary" size="small" @click="openCreateUser">新增用户</el-button>
          </div>
        </template>
        <el-table :data="users" size="small">
          <el-table-column prop="username" label="用户名" min-width="120" />
          <el-table-column label="角色" min-width="160">
            <template #default="{ row }">
              <el-tag v-for="r in row.roles" :key="r" size="small" class="mr-1" :type="r === 'admin' ? 'danger' : 'info'">
                {{ r }}
              </el-tag>
              <span v-if="!row.roles.length" class="text-slate-400">无</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
                {{ row.status === "active" ? "正常" : "禁用" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="170">
            <template #default="{ row }">{{ row.created_at?.replace("T", " ").slice(0, 19) || "—" }}</template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openEditUser(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="removeUser(row)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无用户" />
          </template>
        </el-table>
      </el-card>
    </template>

    <!-- 角色管理 -->
    <template v-if="activeTab === 'roles'">
      <el-card shadow="never">
        <template #header>
          <div class="flex items-center justify-between">
            <span class="font-bold">角色列表</span>
            <el-button type="primary" size="small" @click="openCreateRole">新增角色</el-button>
          </div>
        </template>
        <el-table :data="roles" size="small">
          <el-table-column prop="code" label="编码" width="120" />
          <el-table-column prop="name" label="名称" min-width="120" />
          <el-table-column label="权限码" min-width="240">
            <template #default="{ row }">
              <el-tag v-if="row.perms.includes('*') || row.code === 'admin'" type="danger" size="small">
                全部权限（通配）
              </el-tag>
              <template v-else>
                <el-tag v-for="p in row.perms.slice(0, 5)" :key="p" size="small" class="mr-1">{{ p }}</el-tag>
                <span v-if="row.perms.length > 5" class="text-xs text-slate-400">+{{ row.perms.length - 5 }}</span>
                <span v-if="!row.perms.length" class="text-slate-400">无</span>
              </template>
            </template>
          </el-table-column>
          <el-table-column label="挂载用户" width="140">
            <template #default="{ row }">
              <span>{{ row.users.length ? row.users.join("、") : "—" }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openEditRole(row)">编辑</el-button>
              <el-button size="small" type="danger" plain :disabled="row.code === 'admin'" @click="removeRole(row)">
                删除
              </el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无角色" />
          </template>
        </el-table>
      </el-card>
    </template>

    <!-- 用户弹窗 -->
    <el-dialog v-model="userDialogVisible" :title="editingUser ? `编辑用户 ${editingUser}` : '新增用户'" width="480px">
      <el-form label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="userForm.username" :disabled="!!editingUser" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item :label="editingUser ? '新密码' : '密码'">
          <el-input
            v-model="userForm.password"
            type="password"
            show-password
            :placeholder="editingUser ? '留空不修改' : '至少 6 位'"
          />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.roles" multiple style="width: 100%">
            <el-option v-for="r in roles" :key="r.code" :label="r.name || r.code" :value="r.code" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="userSaving" @click="saveUser">保存</el-button>
      </template>
    </el-dialog>

    <!-- 角色弹窗 -->
    <el-dialog v-model="roleDialogVisible" :title="editingRole ? `编辑角色 ${editingRole}` : '新增角色'" width="560px">
      <el-form label-width="80px">
        <el-form-item label="编码">
          <el-input v-model="roleForm.code" :disabled="!!editingRole" placeholder="小写字母+数字+下划线" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="roleForm.name" placeholder="显示名（可选）" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="roleForm.remark" placeholder="说明（可选）" />
        </el-form-item>
        <el-form-item label="权限码">
          <el-select v-model="roleForm.perms" multiple filterable style="width: 100%" placeholder="选择权限码">
            <el-option v-for="c in permCodes" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="roleSaving" @click="saveRole">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
