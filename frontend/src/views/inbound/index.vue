<template>
  <section class="page" data-module="inbound">
    <header class="page-head">
      <div>
        <h2>入库管理管理</h2>
        <p class="page-desc">维护入库单，围绕入库单号、供应商名称、货物名称、批次号做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记入库单</button>
        <button class="btn" type="button" @click="exportRows">导出入库管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="onSearch">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '状态'" class="status-tag" :class="statusClass(String(row[column]))">{{ row[column] ?? '—' }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <template v-if="actionsFor(String(row.status)).length">
              <button
                v-for="action in actionsFor(String(row.status))"
                :key="action"
                class="link"
                type="button"
                :disabled="actingKey === actionKey(String(row.id), action)"
                @click="runAction(action, row)"
              >
                {{ actingKey === actionKey(String(row.id), action) ? `${action}中` : action }}
              </button>
            </template>
            <span v-else class="muted-text">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无入库管理数据，可先登记入库单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条入库管理记录</span>
      <span v-if="feedback" :class="feedback.type === 'error' ? 'error-text' : 'success-text'">{{ feedback.text }}</span>
    </footer>

    <div v-if="receiveTarget" class="modal-mask" @click.self="closeReceive">
      <div class="modal-card">
        <h3>确认收货</h3>
        <p class="modal-desc">
          入库单号 {{ receiveTarget['入库单号'] }}（当前状态：{{ receiveTarget.status }}），
          请登记到货温度后完成收货。
        </p>
        <label class="filter-item">
          <span>到货温度（℃）</span>
          <input
            v-model="receiveTemperature"
            type="number"
            step="0.1"
            placeholder="如 2.5、-18"
            @keyup.enter="confirmReceive"
          />
        </label>
        <p v-if="receiveError" class="error-text">{{ receiveError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" :disabled="submitting" @click="closeReceive">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="confirmReceive">
            {{ submitting ? '提交中…' : '确认收货' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Feedback = { type: 'error' | 'success'; text: string }

const ENDPOINT = '/api/inbound'
const columns = ["入库单号", "状态", "供应商名称", "货物名称", "批次号", "入库数量", "到货温度", "收货人", "入库时间"]
const stats = [{"label": "今日入库单", "value": 0}, {"label": "待上架单", "value": 0}, {"label": "到货温度不达标", "value": 0}]

// 流转口径：待收货 →（确认收货）→ 已收货 →（安排上架）→ 已上架；
// 待收货/已收货可退回；已上架、已退回为终态，不再给出动作入口。
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  '待收货': ['确认收货', '退回入库'],
  '已收货': ['安排上架', '退回入库'],
  '已上架': [],
  '已退回': [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const feedback = ref<Feedback | null>(null)
const filters = ref<Record<string, string>>({})
const filterFields = ["入库单号", "供应商名称", "货物名称"]

// 正在执行的动作标记：请求返回前按钮禁用，列表页重复点击只放行一次。
const actingKey = ref('')
function actionKey(rowId: string, action: string) {
  return `${rowId}:${action}`
}

function actionsFor(status: string): string[] {
  return ACTIONS_BY_STATUS[status] ?? []
}

function statusClass(status: string) {
  return {
    '待收货': 'status-pending',
    '已收货': 'status-received',
    '已上架': 'status-shelved',
    '已退回': 'status-returned',
  }[status] ?? ''
}

function resetFilters() {
  filters.value = {}
  void onSearch()
}

function onSearch() {
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  feedback.value = { type: 'error', text: '入库单登记入口尚未接入审批流' }
}

// 确认收货必须登记到货温度，先弹窗收集再随动作一起提交。
const receiveTarget = ref<Row | null>(null)
const receiveTemperature = ref('')
const receiveError = ref('')
const submitting = ref(false)

function openReceive(row: Row) {
  receiveTarget.value = row
  receiveTemperature.value = ''
  receiveError.value = ''
}

function closeReceive() {
  if (submitting.value) return
  receiveTarget.value = null
}

async function confirmReceive() {
  if (!receiveTarget.value) return
  receiveError.value = ''
  const temperature = receiveTemperature.value.trim()
  if (!temperature) {
    receiveError.value = '请填写到货温度（数字，如 2.5 或 -18）'
    return
  }
  submitting.value = true
  try {
    const ok = await submitAction(receiveTarget.value, '确认收货', { 到货温度: temperature })
    if (ok) {
      receiveTarget.value = null
    } else if (feedback.value) {
      receiveError.value = feedback.value.text
    }
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  if (action === '确认收货') {
    openReceive(row)
    return
  }
  if (action === '退回入库' && !window.confirm(`确认将入库单 ${row['入库单号']} 退回？退回后不能再确认收货或安排上架。`)) {
    return
  }
  await submitAction(row, action)
}

async function submitAction(row: Row, action: string, extra: Record<string, string> = {}): Promise<boolean> {
  feedback.value = null
  actingKey.value = actionKey(String(row.id), action)
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action, ...extra }),
    })
    // 后端业务拦截仍返回 200 + ok:false，message 里带当前状态与可选动作。
    let payload: { ok?: boolean; message?: string } | null = null
    try {
      payload = await response.json()
    } catch {
      payload = null
    }
    if (!response.ok) {
      throw new Error(payload?.message || '入库管理动作未生效，请稍后重试')
    }
    if (!payload || !payload.ok) {
      feedback.value = { type: 'error', text: payload?.message || '该动作在当前状态下不允许执行' }
      return false
    }
    feedback.value = { type: 'success', text: payload.message || `入库单已${action}` }
    await reload(true)
    return true
  } catch (error) {
    feedback.value = { type: 'error', text: error instanceof Error ? error.message : '入库管理操作失败' }
    return false
  } finally {
    actingKey.value = ''
  }
}

async function reload(keepFeedback = false) {
  if (!keepFeedback) feedback.value = null
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('入库单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    feedback.value = { type: 'error', text: error instanceof Error ? error.message : '入库管理列表读取失败' }
  }
}

onMounted(reload)
</script>

<style scoped>
.status-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  border: 1px solid var(--border);
  white-space: nowrap;
}
.status-pending { color: #b54708; background: #fffaeb; border-color: #fedf89; }
.status-received { color: #175cd3; background: #eff8ff; border-color: #b2ddff; }
.status-shelved { color: #027a48; background: #ecfdf3; border-color: #abefc6; }
.status-returned { color: #b42318; background: #fef3f2; border-color: #fda29b; }
.muted-text { color: var(--muted); }
.success-text { color: #027a48; }
.link:disabled { color: var(--muted); cursor: not-allowed; }

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 360px;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  box-shadow: 0 12px 32px rgba(16, 24, 40, 0.2);
}
.modal-card h3 { margin: 0 0 8px; font-size: 15px; }
.modal-desc { margin: 0 0 12px; color: var(--muted); font-size: 12px; line-height: 1.6; }
.modal-card .filter-item { margin-bottom: 12px; }
.modal-card input { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
</style>
